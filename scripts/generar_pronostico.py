# -*- coding: utf-8 -*-
"""
Genera el pronóstico de precipitación acumulada 72 h del WRF-SMN.

Salida:
- Teselas XYZ (PNG con transparencia) recortadas al polígono de Santa Fe.
- Metadata con la escala del SMN orientada al sector agropecuario.

Cambios importantes:
- La variable PP es precipitación acumulada cada 10 minutos.
  Cada archivo del SMN contiene 6 timesteps de 10 min = 1 hora completa.
  Para obtener la precipitación de cada hora se SUMAN las 6 bandas del
  archivo, no se toma una sola.
- El bbox de trabajo se calcula desde el polígono de Santa Fe.
- El metadata.json declara los bounds REALES del ráster recortado.
- NoData transparente (-9999) con la entrada al principio de la tabla.
- Sin SystemExit(0) silencioso: los errores salen con código 1.
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
from concurrent.futures import ThreadPoolExecutor, as_completed

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

# Margen (en grados) alrededor del bbox del polígono.
MARGEN_BBOX = 0.1

ZOOM_MIN, ZOOM_MAX = 0, 11

MAX_WORKERS = 8

HORAS = list(range(1, 73))

NODATA_VALOR = -9999

# Resolución de la grilla destino (píxeles por grado).
N_PIXELES_POR_GRADO = 60

# ------------------------------------------------------------
# ESCALA DE COLORES
# ------------------------------------------------------------
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
            if os.path.exists(ruta_local) and os.path.getsize(ruta_local) > 100_000:
                return True
            if os.path.exists(ruta_local):
                os.remove(ruta_local)
        except Exception as e:
            log.warning("    Intento %d falló: %s", intento + 1, e)
            time.sleep(2 * (intento + 1))
    return False


def procesar_archivo_pp(ruta_nc, validar_unidades=False):
    """
    Lee la variable PP de un NetCDF del SMN y devuelve la precipitación
    horaria del archivo.

    IMPORTANTE: PP es precipitación acumulada cada 10 minutos. Cada
    archivo contiene 6 timesteps de 10 min (una hora completa). Para
    obtener la precipitación de esa hora, se SUMAN las 6 bandas.
    """
    ds = xr.open_dataset(ruta_nc, engine="netcdf4")

    if "PP" in ds.data_vars:
        pp = ds["PP"]
    else:
        candidatos = [v for v in ds.data_vars
                      if "precip" in v.lower() or v.upper() == "PP"]
        if not candidatos:
            ds.close()
            raise ValueError(f"No se encontró PP en {ruta_nc}. "
                             f"Variables: {list(ds.data_vars)}")
        pp = ds[candidatos[0]]
        log.warning("  Variable PP no encontrada, usando %s", candidatos[0])

    if validar_unidades:
        unidades = pp.attrs.get("units", "").lower()
        validas = ("mm", "millimeter", "kg", "precip")
        if unidades and not any(u in unidades for u in validas):
            log.warning("  Unidades de PP inesperadas: %r", unidades)

    valores = pp.values

    if valores.ndim == 3:
        # Sumar los 6 timesteps de 10 min para obtener la hora completa.
        valores = np.nansum(valores, axis=0)
    elif valores.ndim == 2:
        # Archivo con una sola capa (ej. pp_072.nc con 1 banda).
        valores = np.nan_to_num(valores, nan=0.0)

    valores = valores.astype(np.float32)
    ds.close()
    return valores


# ============================================================
# PROCESAMIENTO PRINCIPAL
# ============================================================
def main():
    # ----------------------------------------------------
    # 0. Leer el polígono y calcular el bbox de trabajo
    # ----------------------------------------------------
    log.info("=" * 60)
    log.info("LEYENDO POLÍGONO DE SANTA FE")
    log.info("=" * 60)

    if not os.path.exists(RUTA_POLIGONO):
        log.error("No se encontró %s. Se aborta.", RUTA_POLIGONO)
        sys.exit(1)

    gdf = gpd.read_file(RUTA_POLIGONO)
    if gdf.crs and str(gdf.crs) != "EPSG:4326":
        gdf = gdf.to_crs("EPSG:4326")
    log.info("  Polígono: %d entidad(es), CRS: %s", len(gdf), gdf.crs)

    lon_min_p, lat_min_p, lon_max_p, lat_max_p = gdf.total_bounds
    log.info("  BBox del polígono: lon [%.4f, %.4f], lat [%.4f, %.4f]",
             lon_min_p, lon_max_p, lat_min_p, lat_max_p)

    LON_MIN = lon_min_p - MARGEN_BBOX
    LON_MAX = lon_max_p + MARGEN_BBOX
    LAT_MIN = lat_min_p - MARGEN_BBOX
    LAT_MAX = lat_max_p + MARGEN_BBOX
    log.info("  BBox de trabajo (+%.2f°): lon [%.4f, %.4f], lat [%.4f, %.4f]",
             MARGEN_BBOX, LON_MIN, LON_MAX, LAT_MIN, LAT_MAX)

    with tempfile.TemporaryDirectory() as tmp:
        archivo_tif = os.path.join(tmp, "pronostico_72h.tif")

        # ------------------------------------------------
        # 1. Corrida más reciente
        # ------------------------------------------------
        log.info("=" * 60)
        log.info("BUSCANDO CORRIDA DISPONIBLE EN EL BUCKET DEL SMN")
        log.info("=" * 60)

        fs = s3fs.S3FileSystem(anon=True)
        hoy = datetime.datetime.now()

        corrida = None
        for dias_atras in range(3):
            fecha = hoy - datetime.timedelta(days=dias_atras)
            anio = fecha.strftime("%Y")
            mes = fecha.strftime("%m")
            dia = fecha.strftime("%d")

            ruta_test = (f"{BUCKET}/DATA/WRF/DET/{anio}/{mes}/{dia}/12/"
                         f"WRFDETAR_10M_{anio}{mes}{dia}_12_072.nc")
            try:
                fs.info(ruta_test)
                corrida = (anio, mes, dia)
                log.info("  Corrida encontrada: %s-%s-%s 12 UTC",
                         anio, mes, dia)
                break
            except Exception:
                log.info("  Corrida %s-%s-%s no disponible", anio, mes, dia)

        if corrida is None:
            log.error("No hay corridas disponibles. Se aborta.")
            sys.exit(1)

        anio, mes, dia = corrida

        # ------------------------------------------------
        # 2. Descarga paralela
        # ------------------------------------------------
        log.info("=" * 60)
        log.info("DESCARGA PARALELA DE 72 ARCHIVOS (workers=%d)", MAX_WORKERS)
        log.info("=" * 60)

        archivos_locales = {}
        t_inicio = time.time()

        def descargar_hora(hora):
            ruta_s3 = (f"{BUCKET}/DATA/WRF/DET/{anio}/{mes}/{dia}/12/"
                       f"WRFDETAR_10M_{anio}{mes}{dia}_12_{hora:03d}.nc")
            ruta_local = os.path.join(tmp, f"pp_{hora:03d}.nc")
            exito = descargar_archivo(fs, ruta_s3, ruta_local)
            return hora, ruta_local if exito else None

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futuros = {executor.submit(descargar_hora, h): h for h in HORAS}
            completados = 0
            for futuro in as_completed(futuros):
                hora, ruta = futuro.result()
                if ruta:
                    archivos_locales[hora] = ruta
                completados += 1
                if completados % 12 == 0:
                    log.info("  Descargados %d/%d", completados, len(HORAS))

        t_fin = time.time()
        log.info("  Descargados %d/%d archivos en %.1f s",
                 len(archivos_locales), len(HORAS), t_fin - t_inicio)

        if len(archivos_locales) < len(HORAS) * 0.9:
            log.error("Menos del 90%% de archivos descargados. Se aborta.")
            sys.exit(1)

        # ------------------------------------------------
        # 3. Estructura del primer archivo
        # ------------------------------------------------
        log.info("=" * 60)
        log.info("LEYENDO ESTRUCTURA DEL PRIMER ARCHIVO")
        log.info("=" * 60)

        primera_hora = min(archivos_locales.keys())
        ds_ref = xr.open_dataset(archivos_locales[primera_hora], engine="netcdf4")

        if "PP" in ds_ref.data_vars:
            log.info("  PP attrs: %s", dict(ds_ref["PP"].attrs))
            muestra = ds_ref["PP"]
            log.info("  PP shape original: %s", muestra.shape)
            if muestra.ndim == 3:
                log.info("  PP timesteps por archivo: %d", muestra.shape[0])
                log.info("  PP rango banda 1: %.4f a %.4f",
                         float(muestra.isel(time=0).min()),
                         float(muestra.isel(time=0).max()))
                suma_hora = np.nansum(muestra.values, axis=0)
                log.info("  PP suma de 6 bandas (1 hora): max=%.4f",
                         float(np.nanmax(suma_hora)))

        lat2d = ds_ref["lat"].values
        lon2d = ds_ref["lon"].values
        if lat2d.ndim == 3:
            lat2d = lat2d[0]
        if lon2d.ndim == 3:
            lon2d = lon2d[0]

        log.info("  Forma de la grilla: %s", lat2d.shape)
        log.info("  lat: %.2f a %.2f", np.min(lat2d), np.max(lat2d))
        log.info("  lon: %.2f a %.2f", np.min(lon2d), np.max(lon2d))

        mascara_bbox = ((lon2d >= LON_MIN) & (lon2d <= LON_MAX) &
                        (lat2d >= LAT_MIN) & (lat2d <= LAT_MAX))
        log.info("  Puntos dentro del bbox: %d", int(np.sum(mascara_bbox)))

        if mascara_bbox.sum() < 100:
            log.error("Muy pocos puntos del WRF dentro del bbox. Se aborta.")
            sys.exit(1)

        ds_ref.close()

        # ------------------------------------------------
        # 4. Acumulación en streaming
        # ------------------------------------------------
        log.info("=" * 60)
        log.info("ACUMULANDO PRECIPITACIÓN EN STREAMING")
        log.info("=" * 60)

        acumulado = np.zeros(lat2d.shape, dtype=np.float32)
        horas_procesadas = 0

        for hora in sorted(archivos_locales.keys()):
            ruta_local = archivos_locales[hora]
            try:
                # Suma las 6 bandas de 10 min para obtener la hora completa.
                capa = procesar_archivo_pp(ruta_local)
                if capa.shape != acumulado.shape:
                    log.warning("  Hora %d: forma inesperada %s, se ignora",
                                hora, capa.shape)
                    os.remove(ruta_local)
                    continue
                acumulado += np.nan_to_num(capa, nan=0.0)
                horas_procesadas += 1
                os.remove(ruta_local)
                if horas_procesadas % 12 == 0:
                    log.info("  Procesadas %d horas | máx acumulado: %.2f mm",
                             horas_procesadas, float(np.nanmax(acumulado)))
            except Exception as e:
                log.warning("  Hora %d: error %s", hora, e)
                if os.path.exists(ruta_local):
                    os.remove(ruta_local)

        log.info("  Total procesadas: %d horas", horas_procesadas)
        log.info("  Máximo acumulado: %.2f mm", float(np.nanmax(acumulado)))

        # ------------------------------------------------
        # 5. Interpolación a grilla regular dentro del bbox
        # ------------------------------------------------
        log.info("=" * 60)
        log.info("INTERPOLANDO A CUADRÍCULA REGULAR")
        log.info("=" * 60)

        N_LON = max(100, int((LON_MAX - LON_MIN) * N_PIXELES_POR_GRADO))
        N_LAT = max(100, int((LAT_MAX - LAT_MIN) * N_PIXELES_POR_GRADO))
        lon_reg = np.linspace(LON_MIN, LON_MAX, N_LON)
        lat_reg = np.linspace(LAT_MIN, LAT_MAX, N_LAT)

        log.info("  Grilla destino: %d x %d (%.0f px/°)",
                 N_LAT, N_LON, N_PIXELES_POR_GRADO)

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

        acumulado_interp = np.where(
            np.isnan(interp_linear), interp_nearest, interp_linear
        ).astype(np.float32)

        log.info("  Máximo interpolado: %.2f mm",
                 float(np.nanmax(acumulado_interp)))

        # ------------------------------------------------
        # 6. DataArray + recorte al polígono
        # ------------------------------------------------
        lluvia_regular = xr.DataArray(
            acumulado_interp,
            dims=["latitude", "longitude"],
            coords={"latitude": lat_reg, "longitude": lon_reg},
            name="PP",
            attrs={"units": "mm", "long_name": "Precipitación acumulada 72h"},
        )
        lluvia_regular = lluvia_regular.rio.write_crs("EPSG:4326")
        lluvia_regular = lluvia_regular.rio.set_spatial_dims(
            x_dim="longitude", y_dim="latitude", inplace=True
        )

        log.info("=" * 60)
        log.info("RECORTANDO AL POLÍGONO")
        log.info("=" * 60)

        lluvia_regular = lluvia_regular.rio.clip(
            gdf.geometry.values,
            gdf.crs,
            drop=False,
            invert=False,
        )
        log.info("  Forma después del clip: %s", lluvia_regular.shape)

        # ------------------------------------------------
        # 6c. NoData y guardado
        # ------------------------------------------------
        lluvia_regular = lluvia_regular.fillna(NODATA_VALOR)
        lluvia_regular = lluvia_regular.rio.write_nodata(NODATA_VALOR)
        lluvia_regular.rio.to_raster(archivo_tif, nodata=NODATA_VALOR)

        arr = lluvia_regular.values
        total = arr.size
        nodata_count = int(np.sum(arr == NODATA_VALOR))
        validos_final = arr[arr != NODATA_VALOR]

        log.info("  Píxeles totales: %d", total)
        log.info("  Píxeles con NoData: %d", nodata_count)
        log.info("  Píxeles válidos: %d", total - nodata_count)
        if len(validos_final) > 0:
            log.info("  Rango de valores válidos: %.2f a %.2f mm",
                     float(np.min(validos_final)),
                     float(np.max(validos_final)))

        if len(validos_final) == 0:
            log.error("El ráster no tiene píxeles válidos. Se aborta.")
            sys.exit(1)

        # ------------------------------------------------
        # 7. Paleta con NoData transparente
        # ------------------------------------------------
        log.info("=" * 60)
        log.info("APLICANDO PALETA DE COLORES")
        log.info("=" * 60)

        archivo_color = os.path.join(tmp, "pronostico_color.tif")

        lineas_color = [f"{NODATA_VALOR} 0 0 0 0"]
        for vmin, vmax, hex_color in ESCALA:
            r, g, b = hex_a_rgb(hex_color)
            lineas_color.append(f"{vmin} {r} {g} {b} 255")

        archivo_tabla = os.path.join(tmp, "paleta.txt")
        with open(archivo_tabla, "w") as f:
            f.write("\n".join(lineas_color))

        subprocess.run([
            "gdaldem", "color-relief",
            archivo_tif,
            archivo_tabla,
            archivo_color,
            "-alpha",
        ], check=True)

        log.info("  Ráster coloreado: %s", archivo_color)

        # ------------------------------------------------
        # 8. Teselas
        # ------------------------------------------------
        log.info("=" * 60)
        log.info("GENERANDO TESELAS")
        log.info("=" * 60)

        if os.path.exists(DIR_TESELAS):
            shutil.rmtree(DIR_TESELAS)

        subprocess.run([
            "gdal2tiles.py",
            "-z", f"{ZOOM_MIN}-{ZOOM_MAX}",
            "-w", "none",
            "-p", "mercator",
            "--xyz",
            "--processes", "4",
            archivo_color,
            DIR_TESELAS,
        ], check=True)

        log.info("  Teselas generadas en %s/", DIR_TESELAS)

        # ------------------------------------------------
        # 9. Metadata con bounds REALES
        # ------------------------------------------------
        os.makedirs(DIR_METADATA, exist_ok=True)

        b = lluvia_regular.rio.bounds()
        bounds_reales = [[b[1], b[0]], [b[3], b[2]]]

        log.info("  Bounds reales del ráster: lon [%.4f, %.4f], lat [%.4f, %.4f]",
                 b[0], b[2], b[1], b[3])

        escala_metadata = []
        for vmin, vmax, color in ESCALA:
            if vmin == 0 and vmax == 0.1:
                label = "Sin precipitación"
            elif vmax == 500:
                label = f"más de {vmin}"
            else:
                label = f"{vmin} - {vmax}"
            escala_metadata.append({
                "min": vmin,
                "max": vmax,
                "color": color,
                "label": label,
            })

        metadata = {
            "fecha_emision": datetime.datetime.now(
                datetime.timezone.utc).isoformat(),
            "corrida_wrf": f"{anio}-{mes}-{dia} 12 UTC",
            "variable": "Precipitación acumulada 72 h",
            "unidad": "mm",
            "bounds": bounds_reales,
            "zoom_min": ZOOM_MIN,
            "zoom_max": ZOOM_MAX,
            "max_mm": float(np.nanmax(acumulado_interp)),
            "horas_procesadas": horas_procesadas,
            "escala": escala_metadata,
            "crs": "EPSG:4326",
            "recortado_a": "Santa Fe",
        }

        ruta_metadata = os.path.join(DIR_METADATA, "metadata.json")
        with open(ruta_metadata, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        log.info("  Metadata: %s", ruta_metadata)
        log.info("  Máximo final: %.2f mm", metadata["max_mm"])

    log.info("=" * 60)
    log.info("PROCESO COMPLETO")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
