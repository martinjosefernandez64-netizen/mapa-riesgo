# -*- coding: utf-8 -*-
"""
Genera el pronóstico de precipitación acumulada 72 h del WRF-SMN.

Genera 4 capas:
- total: acumulado de 72 h (suma de los 3 archivos)
- dia1:  lluvia del día 1 (0-24h)
- dia2:  lluvia del día 2 (24-48h)
- dia3:  lluvia del día 3 (48-72h)

La suma de dia1 + dia2 + dia3 = total.

Fuente:
- WRFDETAR_01H_YYYYMMDD_HH_024.nc
- WRFDETAR_01H_YYYYMMDD_HH_048.nc
- WRFDETAR_01H_YYYYMMDD_HH_072.nc
"""

import os
import sys
import shutil
import subprocess
import json
import logging
import datetime
import tempfile
import time

import numpy as np
import xarray as xr
import rioxarray  # noqa: F401
import s3fs
import geopandas as gpd
from scipy.interpolate import griddata

# ============================================================
# LOGGING
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("pronostico")

# ============================================================
# CONFIGURACIÓN
# ============================================================
BUCKET = "smn-ar-wrf"
DIR_TESELAS = "tiles_pronostico"
DIR_METADATA = "datos/pronostico"
RUTA_POLIGONO = "datos/santa_fe.geojson"

MARGEN_BBOX = 0.1
ZOOM_MIN, ZOOM_MAX = 0, 11

# Corridas en orden de preferencia
HORAS_CORRIDA = ["12", "06", "00", "18"]

# Plazos de los archivos a descargar (24, 48, 72 h)
PLAZOS = ["024", "048", "072"]

NODATA_VALOR = -9999
N_PIXELES_POR_GRADO = 60

ESCALA = [
    (0,   0.1, "#f7f4e9"),
    (0.1, 1,   "#ffffcc"),
    (1,   5,   "#c2e699"),
    (5,   15,  "#78c679"),
    (15,  30,  "#6baed6"),
    (30,  50,  "#4292c6"),
    (50,  75,  "#2171b5"),
    (75,  100, "#08519c"),
    (100, 150, "#d6604d"),
    (150, 500, "#67001f"),
]


# ============================================================
# FUNCIONES AUXILIARES
# ============================================================
def hex_a_rgb(hex_color):
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def descargar_archivo(fs, ruta_s3, ruta_local, max_intentos=3):
    for intento in range(max_intentos):
        try:
            fs.get(ruta_s3, ruta_local)
            if os.path.exists(ruta_local) and os.path.getsize(ruta_local) > 1_000_000:
                return True
            if os.path.exists(ruta_local):
                os.remove(ruta_local)
        except Exception as e:
            log.warning("    Intento %d falló: %s", intento + 1, e)
            time.sleep(2 * (intento + 1))
    return False


def procesar_archivo_pp(ruta_nc):
    """Lee la variable PP del archivo (1 sola banda)."""
    ds = xr.open_dataset(ruta_nc, engine="netcdf4")
    if "PP" not in ds.data_vars:
        ds.close()
        raise ValueError(f"No se encontró PP en {ruta_nc}")
    pp = ds["PP"]
    valores = pp.values
    if valores.ndim == 3:
        valores = valores[0]
    valores = np.nan_to_num(valores, nan=0.0).astype(np.float32)
    ds.close()
    return valores


def interpolar_a_grilla(acumulado, lat2d, lon2d, mascara_bbox,
                        LON_MIN, LON_MAX, LAT_MIN, LAT_MAX):
    """Interpola el array WRF a la grilla regular."""
    N_LON = max(100, int((LON_MAX - LON_MIN) * N_PIXELES_POR_GRADO))
    N_LAT = max(100, int((LAT_MAX - LAT_MIN) * N_PIXELES_POR_GRADO))
    lon_reg = np.linspace(LON_MIN, LON_MAX, N_LON)
    lat_reg = np.linspace(LAT_MIN, LAT_MAX, N_LAT)

    puntos_lon = lon2d[mascara_bbox]
    puntos_lat = lat2d[mascara_bbox]
    valores = acumulado[mascara_bbox]
    validos = np.isfinite(valores)

    grid_lon, grid_lat = np.meshgrid(lon_reg, lat_reg)

    interp_linear = griddata(
        np.column_stack([puntos_lon[validos], puntos_lat[validos]]),
        valores[validos],
        (grid_lon, grid_lat),
        method="linear",
        fill_value=np.nan,
    ).astype(np.float32)

    interp_nearest = griddata(
        np.column_stack([puntos_lon[validos], puntos_lat[validos]]),
        valores[validos],
        (grid_lon, grid_lat),
        method="nearest",
        fill_value=np.nan,
    ).astype(np.float32)

    resultado = np.where(
        np.isnan(interp_linear), interp_nearest, interp_linear
    ).astype(np.float32)

    return resultado, lat_reg, lon_reg


def generar_capa(acumulado, gdf, lat_reg, lon_reg, archivo_tif,
                 directorio_teselas, LON_MIN, LON_MAX, LAT_MIN, LAT_MAX):
    """Genera una capa (GeoTIFF + teselas) a partir de un array interpolado."""
    lluvia = xr.DataArray(
        acumulado,
        dims=["latitude", "longitude"],
        coords={"latitude": lat_reg, "longitude": lon_reg},
        name="PP",
        attrs={"units": "mm"},
    )
    lluvia = lluvia.rio.write_crs("EPSG:4326")
    lluvia = lluvia.rio.set_spatial_dims(
        x_dim="longitude", y_dim="latitude", inplace=True
    )

    lluvia = lluvia.rio.clip(
        gdf.geometry.values, gdf.crs, drop=False, invert=False
    )
    lluvia = lluvia.fillna(NODATA_VALOR)
    lluvia = lluvia.rio.write_nodata(NODATA_VALOR)
    lluvia.rio.to_raster(archivo_tif, nodata=NODATA_VALOR)

    # Paleta
    archivo_color = archivo_tif.replace(".tif", "_color.tif")
    lineas_color = [f"{NODATA_VALOR} 0 0 0 0"]
    for vmin, vmax, hex_color in ESCALA:
        r, g, b = hex_a_rgb(hex_color)
        lineas_color.append(f"{vmin} {r} {g} {b} 255")
    archivo_tabla = archivo_tif.replace(".tif", "_paleta.txt")
    with open(archivo_tabla, "w") as f:
        f.write("\n".join(lineas_color))

    subprocess.run([
        "gdaldem", "color-relief",
        archivo_tif, archivo_tabla, archivo_color, "-alpha",
    ], check=True)

    # Teselas
    if os.path.exists(directorio_teselas):
        shutil.rmtree(directorio_teselas)

    subprocess.run([
        "gdal2tiles.py",
        "-z", f"{ZOOM_MIN}-{ZOOM_MAX}",
        "-w", "none",
        "-p", "mercator",
        "--xyz",
        "--processes", "4",
        archivo_color,
        directorio_teselas,
    ], check=True)

    # Estadísticas
    arr = lluvia.values
    validos = arr[arr != NODATA_VALOR]
    max_val = float(np.max(validos)) if len(validos) > 0 else 0.0

    return max_val


# ============================================================
# MAIN
# ============================================================
def main():
    log.info("=" * 60)
    log.info("LEYENDO POLÍGONO DE SANTA FE")
    log.info("=" * 60)

    if not os.path.exists(RUTA_POLIGONO):
        log.error("No se encontró %s. Se aborta.", RUTA_POLIGONO)
        sys.exit(1)

    gdf = gpd.read_file(RUTA_POLIGONO)
    if gdf.crs and str(gdf.crs) != "EPSG:4326":
        gdf = gdf.to_crs("EPSG:4326")

    lon_min_p, lat_min_p, lon_max_p, lat_max_p = gdf.total_bounds
    LON_MIN = lon_min_p - MARGEN_BBOX
    LON_MAX = lon_max_p + MARGEN_BBOX
    LAT_MIN = lat_min_p - MARGEN_BBOX
    LAT_MAX = lat_max_p + MARGEN_BBOX

    log.info("  BBox: lon [%.4f, %.4f], lat [%.4f, %.4f]",
             LON_MIN, LON_MAX, LAT_MIN, LAT_MAX)

    with tempfile.TemporaryDirectory() as tmp:
        # ------------------------------------------------
        # 1. Buscar corrida
        # ------------------------------------------------
        log.info("=" * 60)
        log.info("BUSCANDO CORRIDA")
        log.info("=" * 60)

        fs = s3fs.S3FileSystem(anon=True)
        hoy = datetime.datetime.now()
        corrida = None

        for dias_atras in range(3):
            fecha = hoy - datetime.timedelta(days=dias_atras)
            anio = fecha.strftime("%Y")
            mes = fecha.strftime("%m")
            dia = fecha.strftime("%d")

            for hora_corrida in HORAS_CORRIDA:
                ruta_test = (f"{BUCKET}/DATA/WRF/DET/{anio}/{mes}/{dia}/{hora_corrida}/"
                             f"WRFDETAR_01H_{anio}{mes}{dia}_{hora_corrida}_072.nc")
                try:
                    fs.info(ruta_test)
                    corrida = (anio, mes, dia, hora_corrida)
                    log.info("  Corrida: %s-%s-%s %s UTC", anio, mes, dia, hora_corrida)
                    break
                except Exception:
                    log.info("  %s-%s-%s %s UTC no disponible", anio, mes, dia, hora_corrida)
            if corrida:
                break

        if not corrida:
            log.error("No hay corridas disponibles.")
            sys.exit(1)

        anio, mes, dia, hora_corrida = corrida

        # ------------------------------------------------
        # 2. Descargar los 3 archivos
        # ------------------------------------------------
        log.info("=" * 60)
        log.info("DESCARGANDO LOS 3 ARCHIVOS (024, 048, 072)")
        log.info("=" * 60)

        archivos_locales = {}
        for plazo in PLAZOS:
            ruta_s3 = (f"{BUCKET}/DATA/WRF/DET/{anio}/{mes}/{dia}/{hora_corrida}/"
                       f"WRFDETAR_01H_{anio}{mes}{dia}_{hora_corrida}_{plazo}.nc")
            ruta_local = os.path.join(tmp, f"pp_{plazo}.nc")
            t0 = time.time()
            ok = descargar_archivo(fs, ruta_s3, ruta_local)
            if not ok:
                log.error("No se pudo descargar %s. Se aborta.", ruta_s3)
                sys.exit(1)
            log.info("  %s descargado (%.1f MB, %.1fs)",
                     plazo, os.path.getsize(ruta_local) / 1024 / 1024,
                     time.time() - t0)
            archivos_locales[plazo] = ruta_local

        # ------------------------------------------------
        # 3. Leer estructura
        # ------------------------------------------------
        log.info("=" * 60)
        log.info("LEYENDO ESTRUCTURA")
        log.info("=" * 60)

        ds_ref = xr.open_dataset(archivos_locales["072"], engine="netcdf4")
        lat2d = ds_ref["lat"].values
        lon2d = ds_ref["lon"].values
        if lat2d.ndim == 3:
            lat2d = lat2d[0]
        if lon2d.ndim == 3:
            lon2d = lon2d[0]
        ds_ref.close()

        mascara_bbox = ((lon2d >= LON_MIN) & (lon2d <= LON_MAX) &
                        (lat2d >= LAT_MIN) & (lat2d <= LAT_MAX))

        log.info("  Grilla WRF: %s", lat2d.shape)
        log.info("  Puntos en bbox: %d", int(np.sum(mascara_bbox)))

        # ------------------------------------------------
        # 4. Leer los 3 archivos y calcular capas
        # ------------------------------------------------
        log.info("=" * 60)
        log.info("CALCULANDO CAPAS")
        log.info("=" * 60)

        pp_024 = procesar_archivo_pp(archivos_locales["024"])
        pp_048 = procesar_archivo_pp(archivos_locales["048"])
        pp_072 = procesar_archivo_pp(archivos_locales["072"])

        # Interpretación: cada archivo es acumulado desde t=0.
        # - Día 1 = 01H_024
        # - Día 2 = 01H_048 - 01H_024
        # - Día 3 = 01H_072 - 01H_048
        # - Total = día1 + día2 + día3 = 01H_072

        dia1 = pp_024
        dia2 = pp_048 - pp_024
        dia3 = pp_072 - pp_048

        # Corregir valores negativos (por ruido numérico)
        dia2 = np.clip(dia2, 0, None)
        dia3 = np.clip(dia3, 0, None)

        total = dia1 + dia2 + dia3

        log.info("  Máximo crudo día 1: %.2f mm", float(np.nanmax(dia1[mascara_bbox])))
        log.info("  Máximo crudo día 2: %.2f mm", float(np.nanmax(dia2[mascara_bbox])))
        log.info("  Máximo crudo día 3: %.2f mm", float(np.nanmax(dia3[mascara_bbox])))
        log.info("  Máximo crudo total: %.2f mm", float(np.nanmax(total[mascara_bbox])))

        # ------------------------------------------------
        # 5. Interpolar las 4 capas
        # ------------------------------------------------
        log.info("=" * 60)
        log.info("INTERPOLANDO LAS 4 CAPAS")
        log.info("=" * 60)

        capas = {}
        lat_reg = lon_reg = None

        for nombre, arr in [("dia1", dia1), ("dia2", dia2),
                            ("dia3", dia3), ("total", total)]:
            log.info("  Interpolando %s...", nombre)
            interp, lat_reg, lon_reg = interpolar_a_grilla(
                arr, lat2d, lon2d, mascara_bbox,
                LON_MIN, LON_MAX, LAT_MIN, LAT_MAX
            )
            capas[nombre] = interp
            log.info("    Máx interpolado %s: %.2f mm",
                     nombre, float(np.nanmax(interp)))

        # ------------------------------------------------
        # 6. Generar teselas para cada capa
        # ------------------------------------------------
        log.info("=" * 60)
        log.info("GENERANDO TESELAS")
        log.info("=" * 60)

        maximos = {}
        for nombre in ["total", "dia1", "dia2", "dia3"]:
            log.info("  Generando capa %s...", nombre)
            dir_teselas = os.path.join(DIR_TESELAS, nombre)
            archivo_tif = os.path.join(tmp, f"{nombre}.tif")
            maximos[nombre] = generar_capa(
                capas[nombre], gdf, lat_reg, lon_reg,
                archivo_tif, dir_teselas,
                LON_MIN, LON_MAX, LAT_MIN, LAT_MAX
            )
            log.info("    Máximo dentro del polígono %s: %.2f mm",
                     nombre, maximos[nombre])

        # ------------------------------------------------
        # 7. Metadata
        # ------------------------------------------------
        os.makedirs(DIR_METADATA, exist_ok=True)

        b = (
            float(lon_reg[0]), float(lat_reg[0]),
            float(lon_reg[-1]), float(lat_reg[-1])
        )
        bounds_reales = [[b[1], b[0]], [b[3], b[2]]]

        escala_metadata = []
        for vmin, vmax, color in ESCALA:
            if vmin == 0 and vmax == 0.1:
                label = "Sin precipitación"
            elif vmax == 500:
                label = f"más de {vmin}"
            else:
                label = f"{vmin} - {vmax}"
            escala_metadata.append({
                "min": vmin, "max": vmax, "color": color, "label": label,
            })

        metadata = {
            "fecha_emision": datetime.datetime.now(
                datetime.timezone.utc).isoformat(),
            "corrida_wrf": f"{anio}-{mes}-{dia} {hora_corrida} UTC",
            "variable": "Precipitación acumulada",
            "unidad": "mm",
            "bounds": bounds_reales,
            "zoom_min": ZOOM_MIN,
            "zoom_max": ZOOM_MAX,
            "capas": {
                "total": {"label": "Total 72h", "max_mm": maximos["total"]},
                "dia1":  {"label": "Día 1 (0-24h)",  "max_mm": maximos["dia1"]},
                "dia2":  {"label": "Día 2 (24-48h)", "max_mm": maximos["dia2"]},
                "dia3":  {"label": "Día 3 (48-72h)", "max_mm": maximos["dia3"]},
            },
            "max_mm": maximos["total"],
            "escala": escala_metadata,
            "crs": "EPSG:4326",
            "recortado_a": "Santa Fe",
        }

        ruta_metadata = os.path.join(DIR_METADATA, "metadata.json")
        with open(ruta_metadata, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        log.info("  Metadata: %s", ruta_metadata)

    log.info("=" * 60)
    log.info("PROCESO COMPLETO")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
