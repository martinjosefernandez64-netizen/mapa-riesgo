# -*- coding: utf-8 -*-
"""
Genera el pronóstico de precipitación acumulada 72 h del WRF-SMN.

Salida:
- Teselas XYZ (PNG con transparencia) recortadas al polígono de Santa Fe.
- Metadata con la escala del SMN orientada al sector agropecuario.

Optimizaciones:
- Descarga paralela de los 72 archivos 10M.
- Acumulación en streaming.
- Borrado inmediato de cada NetCDF.
- Sin reproyección: se trabaja en EPSG:4326 (WGS84).
- Paleta aplicada directamente sobre el ráster continuo, sin reclasificación.
- Enmascaramiento real con rasterio.mask (no solo recorte del bbox).
- NoData explícito (-9999) para que gdaldem lo trate correctamente.
"""

import os
import subprocess
import json
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
# CONFIGURACIÓN
# ============================================================
BUCKET = "smn-ar-wrf"
DIR_TESELAS = "tiles_pronostico"
DIR_METADATA = "datos/pronostico"
RUTA_POLIGONO = "datos/santa_fe.geojson"

# Bounding box de Santa Fe con margen
LON_MIN, LON_MAX = -63.5, -58.5
LAT_MIN, LAT_MAX = -34.5, -27.5

# Niveles de zoom para las teselas
ZOOM_MIN, ZOOM_MAX = 0, 11

# Cantidad de descargas paralelas
MAX_WORKERS = 8

# Horas del pronóstico (1 a 72). El _000 es condición inicial.
HORAS = list(range(1, 73))

# Valor centinela para NoData. Se elige fuera del rango real de
# precipitación (0 a ~500 mm) para que gdaldem no lo confunda.
NODATA_VALOR = -9999

# ------------------------------------------------------------
# ESCALA DE COLORES (adaptada del SMN para el sector agropecuario)
# Cada entrada: (límite_inferior, límite_superior, color_hex)
# Los valores son los umbrales inferiores de cada categoría.
# gdaldem asigna a cada píxel el color del umbral inmediatamente inferior.
# ------------------------------------------------------------
ESCALA = [
    (0,   0.1, "#f7f4e9"),   # Sin precipitación
    (0.1, 1,   "#ffffcc"),   # Trazas
    (1,   5,   "#c2e699"),   # Muy baja
    (5,   15,  "#78c679"),   # Baja
    (15,  30,  "#6baed6"),   # Moderada
    (30,  50,  "#4292c6"),   # Moderada-alta
    (50,  75,  "#2171b5"),   # Alta
    (75,  100, "#08519c"),   # Muy alta
    (100, 150, "#d6604d"),   # Intensa
    (150, 500, "#67001f"),   # Extrema
]


# ============================================================
# FUNCIONES AUXILIARES
# ============================================================
def hex_a_rgb(hex_color):
    """Convierte #RRGGBB a tupla (R, G, B)."""
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def descargar_archivo(fs, ruta_s3, ruta_local, max_intentos=3):
    """Descarga un archivo con reintentos."""
    for intento in range(max_intentos):
        try:
            fs.get(ruta_s3, ruta_local)
            if os.path.exists(ruta_local) and os.path.getsize(ruta_local) > 100_000:
                return True
            if os.path.exists(ruta_local):
                os.remove(ruta_local)
        except Exception as e:
            print(f"    Intento {intento+1} falló: {e}")
            time.sleep(2 * (intento + 1))
    return False


def procesar_archivo_pp(ruta_nc):
    """Lee la variable PP de un NetCDF del SMN."""
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

    valores = pp.values
    if valores.ndim == 3:
        valores = valores[0]
    valores = valores.astype(np.float32)

    ds.close()
    return valores


# ============================================================
# PROCESAMIENTO PRINCIPAL
# ============================================================
with tempfile.TemporaryDirectory() as tmp:
    archivo_tif = os.path.join(tmp, "pronostico_72h.tif")

    # --------------------------------------------------------
    # 1. Determinar la corrida más reciente disponible
    # --------------------------------------------------------
    print("=" * 60)
    print("BUSCANDO CORRIDA DISPONIBLE EN EL BUCKET DEL SMN")
    print("=" * 60)

    fs = s3fs.S3FileSystem(anon=True)
    hoy = datetime.datetime.now()

    corrida = None
    for dias_atras in range(3):
        fecha = hoy - datetime.timedelta(days=dias_atras)
        anio, mes, dia = fecha.strftime("%Y"), fecha.strftime("%m"), fecha.strftime("%d")

        ruta_test = (f"{BUCKET}/DATA/WRF/DET/{anio}/{mes}/{dia}/12/"
                     f"WRFDETAR_10M_{anio}{mes}{dia}_12_072.nc")
        try:
            fs.info(ruta_test)
            corrida = (anio, mes, dia)
            print(f"  Corrida encontrada: {anio}-{mes}-{dia} 12 UTC")
            break
        except Exception:
            print(f"  Corrida {anio}-{mes}-{dia} no disponible")

    if corrida is None:
        print("No hay corridas disponibles. Se conserva la versión anterior.")
        raise SystemExit(0)

    anio, mes, dia = corrida

    # --------------------------------------------------------
    # 2. Descarga paralela de los 72 archivos
    # --------------------------------------------------------
    print(f"\n{'=' * 60}")
    print(f"DESCARGA PARALELA DE 72 ARCHIVOS (workers={MAX_WORKERS})")
    print(f"{'=' * 60}")

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
                print(f"  Descargados {completados}/{len(HORAS)}")

    t_fin = time.time()
    print(f"\n  Descargados {len(archivos_locales)}/{len(HORAS)} archivos "
          f"en {t_fin - t_inicio:.1f} s")

    if len(archivos_locales) < len(HORAS) * 0.9:
        print("Menos del 90% de archivos descargados. Abortando.")
        raise SystemExit(0)

    # --------------------------------------------------------
    # 3. Leer la estructura del primer archivo
    # --------------------------------------------------------
    print(f"\n{'=' * 60}")
    print("LEYENDO ESTRUCTURA DEL PRIMER ARCHIVO")
    print(f"{'=' * 60}")

    primera_hora = min(archivos_locales.keys())
    ds_ref = xr.open_dataset(archivos_locales[primera_hora], engine="netcdf4")
    lat2d = ds_ref["lat"].values
    lon2d = ds_ref["lon"].values

    if lat2d.ndim == 3:
        lat2d = lat2d[0]
    if lon2d.ndim == 3:
        lon2d = lon2d[0]

    print(f"  Forma de la grilla: {lat2d.shape}")
    print(f"  lat: {np.min(lat2d):.2f} a {np.max(lat2d):.2f}")
    print(f"  lon: {np.min(lon2d):.2f} a {np.max(lon2d):.2f}")

    mascara_bbox = ((lon2d >= LON_MIN) & (lon2d <= LON_MAX) &
                    (lat2d >= LAT_MIN) & (lat2d <= LAT_MAX))
    print(f"  Puntos dentro del bbox: {int(np.sum(mascara_bbox))}")

    ds_ref.close()

    # --------------------------------------------------------
    # 4. Acumulación en streaming
    # --------------------------------------------------------
    print(f"\n{'=' * 60}")
    print("ACUMULANDO PRECIPITACIÓN EN STREAMING")
    print(f"{'=' * 60}")

    acumulado = np.zeros(lat2d.shape, dtype=np.float32)
    horas_procesadas = 0

    for hora in sorted(archivos_locales.keys()):
        ruta_local = archivos_locales[hora]
        try:
            capa = procesar_archivo_pp(ruta_local)
            if capa.shape != acumulado.shape:
                print(f"  Hora {hora}: forma inesperada {capa.shape}, se ignora")
                os.remove(ruta_local)
                continue

            acumulado += np.nan_to_num(capa, nan=0.0)
            horas_procesadas += 1
            os.remove(ruta_local)

            if horas_procesadas % 12 == 0:
                print(f"  Procesadas {horas_procesadas} horas | "
                      f"máx acumulado: {np.nanmax(acumulado):.2f} mm")

        except Exception as e:
            print(f"  Hora {hora}: error {e}")
            if os.path.exists(ruta_local):
                os.remove(ruta_local)

    print(f"\n  Total procesadas: {horas_procesadas} horas")
    print(f"  Máximo acumulado: {np.nanmax(acumulado):.2f} mm")
    print(f"  Media acumulada:  {np.nanmean(acumulado):.4f} mm")

    # --------------------------------------------------------
    # 5. Recortar al bbox e interpolar
    # --------------------------------------------------------
    print(f"\n{'=' * 60}")
    print("RECORTANDO E INTERPOLANDO A CUADRÍCULA REGULAR")
    print(f"{'=' * 60}")

    N_LON, N_LAT = 280, 340
    lon_reg = np.linspace(LON_MIN, LON_MAX, N_LON)
    lat_reg = np.linspace(LAT_MIN, LAT_MAX, N_LAT)

    puntos_lon = lon2d[mascara_bbox]
    puntos_lat = lat2d[mascara_bbox]
    valores = acumulado[mascara_bbox]

    validos = np.isfinite(valores)
    grid_lon, grid_lat = np.meshgrid(lon_reg, lat_reg)

    acumulado_interp = griddata(
        np.column_stack([puntos_lon[validos], puntos_lat[validos]]),
        valores[validos],
        (grid_lon, grid_lat),
        method="linear",
        fill_value=np.nan,
    ).astype(np.float32)

    print(f"  Cuadrícula interpolada: {acumulado_interp.shape}")
    print(f"  Máximo interpolado: {np.nanmax(acumulado_interp):.2f} mm")

    # --------------------------------------------------------
    # 6. Construir DataArray en EPSG:4326
    # --------------------------------------------------------
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

    # --------------------------------------------------------
    # 6b. Enmascarar con el polígono de Santa Fe (rasterio.mask)
    # --------------------------------------------------------
    print(f"\n{'=' * 60}")
    print("RECORTANDO AL POLÍGONO DE SANTA FE")
    print(f"{'=' * 60}")

    # Guardar GeoTIFF continuo con NaN antes de enmascarar
    lluvia_regular = lluvia_regular.rio.write_nodata(np.nan)
    lluvia_regular.rio.to_raster(archivo_tif, nodata=np.nan)
    print(f"  GeoTIFF continuo: {archivo_tif}")

    if os.path.exists(RUTA_POLIGONO):
        import rasterio
        from rasterio.mask import mask as rio_mask

        gdf = gpd.read_file(RUTA_POLIGONO)
        print(f"  Polígono cargado: {len(gdf)} entidad(es), CRS: {gdf.crs}")

        if gdf.crs and str(gdf.crs) != "EPSG:4326":
            gdf = gdf.to_crs("EPSG:4326")
            print(f"  Polígono reproyectado a EPSG:4326")

        # Enmascarar con rasterio (garantiza NoData fuera del polígono)
        with rasterio.open(archivo_tif) as src:
            geoms = [geom.__geo_interface__ for geom in gdf.geometry]
            out_image, out_transform = rio_mask(
                src, geoms, crop=True, nodata=np.nan, filled=True
            )
            out_meta = src.meta.copy()
            out_meta.update({
                "height": out_image.shape[1],
                "width": out_image.shape[2],
                "transform": out_transform,
                "nodata": np.nan,
            })

        with rasterio.open(archivo_tif, "w", **out_meta) as dest:
            dest.write(out_image)

        print(f"  Recorte aplicado. Forma después del clip: {out_image.shape}")
    else:
        print(f"  ADVERTENCIA: no se encontró {RUTA_POLIGONO}")

    # --------------------------------------------------------
    # 6c. Reemplazar NaN por NoData explícito para gdaldem
    # --------------------------------------------------------
    # gdaldem maneja mal NaN, así que usamos un centinela fuera
    # del rango real de precipitación.

    lluvia_enmascarada = rioxarray.open_rasterio(archivo_tif, masked=True)
    lluvia_enmascarada = lluvia_enmascarada.fillna(NODATA_VALOR)
    lluvia_enmascarada = lluvia_enmascarada.rio.write_nodata(NODATA_VALOR)
    lluvia_enmascarada.rio.to_raster(archivo_tif, nodata=NODATA_VALOR)

    print(f"  GeoTIFF con NoData={NODATA_VALOR}: {archivo_tif}")

    # --------------------------------------------------------
    # 7. Aplicar paleta de colores sobre el ráster continuo
    # --------------------------------------------------------
    print(f"\n{'=' * 60}")
    print("APLICANDO PALETA DE COLORES")
    print(f"{'=' * 60}")

    archivo_color = os.path.join(tmp, "pronostico_color.tif")

    # Tabla de colores: valor R G B A
    # Los valores son los umbrales inferiores de cada categoría.
    # El valor -9999 corresponde al NoData y se pinta con alfa 0
    # (totalmente transparente).
    lineas_color = []
    for vmin, vmax, hex_color in ESCALA:
        r, g, b = hex_a_rgb(hex_color)
        lineas_color.append(f"{vmin} {r} {g} {b} 255")
    lineas_color.append(f"{NODATA_VALOR} 0 0 0 0")
    tabla_color = "\n".join(lineas_color)

    archivo_tabla = os.path.join(tmp, "paleta.txt")
    with open(archivo_tabla, "w") as f:
        f.write(tabla_color)

    print(f"  Tabla de colores ({len(lineas_color)} categorías):")
    for linea in lineas_color:
        print(f"    {linea}")

    subprocess.run([
        "gdaldem", "color-relief",
        archivo_tif,
        archivo_tabla,
        archivo_color,
        "-nearest_color_entry",
    ], check=True)

    print(f"  Ráster coloreado: {archivo_color}")

    # --------------------------------------------------------
    # 8. Generar teselas
    # --------------------------------------------------------
    print(f"\n{'=' * 60}")
    print("GENERANDO TESELAS")
    print(f"{'=' * 60}")

    if os.path.exists(DIR_TESELAS):
        subprocess.run(["rm", "-rf", DIR_TESELAS], check=True)

    subprocess.run([
        "gdal2tiles.py",
        "-z", f"{ZOOM_MIN}-{ZOOM_MAX}",
        "-w", "none",
        "-p", "mercator",
        "--processes", "4",
        archivo_color,
        DIR_TESELAS,
    ], check=True)

    print(f"  Teselas generadas en {DIR_TESELAS}/")

    # --------------------------------------------------------
    # 9. Metadata con la escala
    # --------------------------------------------------------
    os.makedirs(DIR_METADATA, exist_ok=True)

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
        "bounds": [[LAT_MIN, LON_MIN], [LAT_MAX, LON_MAX]],
        "zoom_min": ZOOM_MIN,
        "zoom_max": ZOOM_MAX,
        "max_mm": float(np.nanmax(acumulado_interp)),
        "horas_procesadas": horas_procesadas,
        "escala": escala_metadata,
        "crs": "EPSG:4326",
        "recortado_a": "Santa Fe" if os.path.exists(RUTA_POLIGONO) else None,
    }

    ruta_metadata = os.path.join(DIR_METADATA, "metadata.json")
    with open(ruta_metadata, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    print(f"\n  Metadata: {ruta_metadata}")
    print(f"  Máximo final: {metadata['max_mm']:.2f} mm")

print("\n" + "=" * 60)
print("PROCESO COMPLETO")
print("=" * 60)
