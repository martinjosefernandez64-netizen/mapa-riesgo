# -*- coding: utf-8 -*-
"""
Genera el pronóstico de precipitación acumulada 72 h del WRF-SMN.

Optimizaciones:
- Descarga paralela de los 72 archivos 10M (más livianos que 01H)
- Acumulación en streaming: nunca se guardan las 72 capas en memoria
- Borrado inmediato de cada NetCDF tras leerlo
- Reintentos con espera ante fallos transitorios del bucket
- Uso de archivos temporales que se eliminan automáticamente

Se ejecuta desde GitHub Actions y publica teselas XYZ + metadata.
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

# ============================================================
# CONFIGURACIÓN
# ============================================================
BUCKET = "smn-ar-wrf"
DIR_TESELAS = "tiles_pronostico"
DIR_METADATA = "datos/pronostico"

# Bounding box de Santa Fe con margen
LON_MIN, LON_MAX = -63.5, -58.5
LAT_MIN, LAT_MAX = -34.5, -27.5

# Niveles de zoom para las teselas
ZOOM_MIN, ZOOM_MAX = 0, 11

# Escala para conversión a 8 bits
MAX_MM = 150.0

# Cantidad de descargas paralelas (ajustar según ancho de banda)
MAX_WORKERS = 8

# Horas del pronóstico (1 a 72). El _000 es condición inicial, no se usa.
HORAS = list(range(1, 73))


# ============================================================
# FUNCIONES AUXILIARES
# ============================================================
def descargar_archivo(fs, ruta_s3, ruta_local, max_intentos=3):
    """Descarga un archivo con reintentos. Devuelve True si tuvo éxito."""
    for intento in range(max_intentos):
        try:
            fs.get(ruta_s3, ruta_local)
            if os.path.exists(ruta_local) and os.path.getsize(ruta_local) > 100_000:
                return True
            if os.path.exists(ruta_local):
                os.remove(ruta_local)
        except Exception as e:
            print(f"    Intento {intento+1} falló: {e}")
            time.sleep(2 * (intento + 1))  # espera creciente
    return False


def procesar_archivo_pp(ruta_nc, mascara=None):
    """
    Lee la variable PP de un NetCDF del SMN y devuelve el array 2D.
    Si se pasa mascara, la aplica.
    """
    ds = xr.open_dataset(ruta_nc, engine="netcdf4")

    # Detectar nombre real de la variable de precipitación
    if "PP" in ds.data_vars:
        pp = ds["PP"]
    else:
        # Buscar variantes por si el SMN cambia el nombre
        candidatos = [v for v in ds.data_vars
                      if "precip" in v.lower() or v.upper() == "PP"]
        if not candidatos:
            ds.close()
            raise ValueError(f"No se encontró PP en {ruta_nc}. "
                             f"Variables: {list(ds.data_vars)}")
        pp = ds[candidatos[0]]

    # Convertir a array 2D
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

        # Verificar que existe el archivo de la hora 72
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
        print("Menos del 90% de archivos descargados. Abortando para evitar "
              "un acumulado incompleto.")
        raise SystemExit(0)

    # --------------------------------------------------------
    # 3. Leer el primer archivo para conocer la estructura
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

    # Máscara geográfica del bbox (misma forma que la grilla WRF)
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

    # Inicializar acumulador con la forma de la grilla WRF
    acumulado = np.zeros(lat2d.shape, dtype=np.float32)
    horas_procesadas = 0

    for hora in sorted(archivos_locales.keys()):
        ruta_local = archivos_locales[hora]
        try:
            capa = procesar_archivo_pp(ruta_local)
            if capa.shape != acumulado.shape:
                print(f"  Hora {hora}: forma inesperada {capa.shape}, "
                      f"se ignora")
                os.remove(ruta_local)
                continue

            acumulado += np.nan_to_num(capa, nan=0.0)
            horas_procesadas += 1

            # Borrar inmediatamente para liberar disco
            os.remove(ruta_local)

            if horas_procesadas % 12 == 0:
                print(f"  Procesadas {horas_procesadas} horas | "
                      f"máx acumulado hasta ahora: {np.nanmax(acumulado):.2f} mm")

        except Exception as e:
            print(f"  Hora {hora}: error {e}")
            if os.path.exists(ruta_local):
                os.remove(ruta_local)

    print(f"\n  Total procesadas: {horas_procesadas} horas")
    print(f"  Máximo acumulado: {np.nanmax(acumulado):.2f} mm")
    print(f"  Media acumulada:  {np.nanmean(acumulado):.4f} mm")

    # --------------------------------------------------------
    # 5. Recortar al bbox de Santa Fe e interpolar
    # --------------------------------------------------------
    print(f"\n{'=' * 60}")
    print("RECORTANDO E INTERPOLANDO A CUADRÍCULA REGULAR")
    print(f"{'=' * 60}")

    from scipy.interpolate import griddata

    N_LON, N_LAT = 280, 340
    lon_reg = np.linspace(LON_MIN, LON_MAX, N_LON)
    lat_reg = np.linspace(LAT_MIN, LAT_MAX, N_LAT)

    # Puntos válidos dentro del bbox
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
        fill_value=0.0,
    ).astype(np.float32)

    print(f"  Cuadrícula interpolada: {acumulado_interp.shape}")
    print(f"  Máximo interpolado: {np.nanmax(acumulado_interp):.2f} mm")

    # --------------------------------------------------------
    # 6. Construir DataArray y reproyectar a Faja 4
    # --------------------------------------------------------
    print(f"\n{'=' * 60}")
    print("REPROYECTANDO A POSGAR 2007 / FAJA 4")
    print(f"{'=' * 60}")

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

    lluvia_5347 = lluvia_regular.rio.reproject("EPSG:5347")
    lluvia_5347 = lluvia_5347.rio.write_nodata(np.nan)
    lluvia_5347.rio.to_raster(archivo_tif, nodata=np.nan)
    print(f"  GeoTIFF temporal: {archivo_tif}")

    # --------------------------------------------------------
    # 7. Convertir a 8 bits y generar teselas
    # --------------------------------------------------------
    print(f"\n{'=' * 60}")
    print("GENERANDO TESELAS")
    print(f"{'=' * 60}")

    if os.path.exists(DIR_TESELAS):
        subprocess.run(["rm", "-rf", DIR_TESELAS], check=True)

    archivo_vrt = os.path.join(tmp, "pronostico_8bit.vrt")
    subprocess.run([
        "gdal_translate",
        "-of", "VRT",
        "-ot", "Byte",
        "-scale", "0", str(MAX_MM), "0", "255",
        archivo_tif,
        archivo_vrt,
    ], check=True)

    subprocess.run([
        "gdal2tiles.py",
        "-z", f"{ZOOM_MIN}-{ZOOM_MAX}",
        "-w", "none",
        "-p", "mercator",
        "--processes", "4",
        archivo_vrt,
        DIR_TESELAS,
    ], check=True)

    # --------------------------------------------------------
    # 8. Metadata
    # --------------------------------------------------------
    os.makedirs(DIR_METADATA, exist_ok=True)
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
    }
    with open(os.path.join(DIR_METADATA, "metadata.json"),
              "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    print(f"\n  Metadata: {DIR_METADATA}/metadata.json")
    print(f"  Máximo final: {metadata['max_mm']:.2f} mm")

print("\n" + "=" * 60)
print("PROCESO COMPLETO")
print("=" * 60)
