# -*- coding: utf-8 -*-
"""
Genera el pronóstico de precipitación acumulada 72 h del WRF-SMN
y lo publica como teselas XYZ + metadata para GitHub Pages.
Se ejecuta automáticamente desde GitHub Actions.
"""

import os
import subprocess
import json
import datetime
import tempfile
import numpy as np
import xarray as xr
import rioxarray  # noqa: F401
import s3fs
from scipy.interpolate import griddata

# ============================================================
# CONFIGURACIÓN
# ============================================================
BUCKET = "smn-ar-wrf"
DIR_TESELAS = "tiles_pronostico"
DIR_METADATA = "datos/pronostico"

# Bounding box de Santa Fe con margen
LON_MIN, LON_MAX = -63.5, -58.5
LAT_MIN, LAT_MAX = -34.5, -27.5

# Resolución de la cuadrícula regular de interpolación
N_LON, N_LAT = 280, 340

# Niveles de zoom para las teselas
ZOOM_MIN, ZOOM_MAX = 0, 11

# ============================================================
# PROCESAMIENTO PRINCIPAL (todo en directorio temporal)
# ============================================================
with tempfile.TemporaryDirectory() as tmp:
    archivo_nc = os.path.join(tmp, "pronostico_smn_72h.nc")
    archivo_tif = os.path.join(tmp, "pronostico_72h.tif")

    # ---------- 1. Descarga del WRF ----------
    print("Buscando archivo en el bucket S3 del SMN...")
    fs = s3fs.S3FileSystem(anon=True)
    hoy = datetime.datetime.now()

    def descargar_wrf(anio, mes, dia, destino, max_intentos=3):
        for intento in range(max_intentos):
            try:
                ruta_s3 = (
                    f"{BUCKET}/DATA/WRF/DET/{anio}/{mes}/{dia}/12/"
                    f"WRFDETAR_01H_{anio}{mes}{dia}_12_072.nc"
                )
                print(f"  Intento {intento+1}: {ruta_s3}")
                fs.get(ruta_s3, destino)
                if os.path.getsize(destino) > 1_000_000:
                    return True
                os.remove(destino)
            except Exception as e:
                print(f"  Falló: {e}")
        return False

    anio, mes, dia = hoy.strftime("%Y"), hoy.strftime("%m"), hoy.strftime("%d")
    exito = descargar_wrf(anio, mes, dia, archivo_nc)

    if not exito:
        print("Corrida de hoy no disponible. Intentando ayer...")
        ayer = hoy - datetime.timedelta(days=1)
        anio, mes, dia = ayer.strftime("%Y"), ayer.strftime("%m"), ayer.strftime("%d")
        exito = descargar_wrf(anio, mes, dia, archivo_nc)

    if not exito:
        print("No se pudo descargar el WRF. Se conserva la versión anterior.")
        raise SystemExit(0)

    print(f"NetCDF temporal: {os.path.getsize(archivo_nc)/1024/1024:.2f} MB")

    # ---------- 2. Lectura y procesamiento ----------
    ds = xr.open_dataset(archivo_nc, engine="netcdf4")
    lluvia = ds["PP"]
    lat2d = ds["lat"]
    lon2d = ds["lon"]

    if "time" in lat2d.dims:
        lat2d = lat2d.isel(time=0)
        lon2d = lon2d.isel(time=0)

    mask = ((lon2d >= LON_MIN) & (lon2d <= LON_MAX) &
            (lat2d >= LAT_MIN) & (lat2d <= LAT_MAX))
    rows = np.where(mask.any(axis=1))[0]
    cols = np.where(mask.any(axis=0))[0]

    if len(rows) == 0 or len(cols) == 0:
        print("Sin puntos en el bbox. Se conserva la versión anterior.")
        raise SystemExit(0)

    lluvia_sf = lluvia.isel(y=slice(rows[0], rows[-1] + 1),
                            x=slice(cols[0], cols[-1] + 1))
    lat_sub = lat2d.isel(y=slice(rows[0], rows[-1] + 1),
                         x=slice(cols[0], cols[-1] + 1))
    lon_sub = lon2d.isel(y=slice(rows[0], rows[-1] + 1),
                         x=slice(cols[0], cols[-1] + 1))

    mask_sub = ((lon_sub >= LON_MIN) & (lon_sub <= LON_MAX) &
                (lat_sub >= LAT_MIN) & (lat_sub <= LAT_MAX))
    lluvia_sf = lluvia_sf.where(mask_sub, drop=False)

    # ---------- 3. Interpolación a cuadrícula regular ----------
    lon_reg = np.linspace(LON_MIN, LON_MAX, N_LON)
    lat_reg = np.linspace(LAT_MIN, LAT_MAX, N_LAT)
    dim_tiempo = "time" if "time" in lluvia_sf.dims else None

    def interpolar_capa(valores_2d):
        points = np.column_stack([lon_sub.values.ravel(), lat_sub.values.ravel()])
        values = valores_2d.ravel()
        valid = ~np.isnan(values)
        if valid.sum() < 10:
            return np.full((N_LAT, N_LON), np.nan)
        grid_lon, grid_lat = np.meshgrid(lon_reg, lat_reg)
        return griddata(points[valid], values[valid],
                        (grid_lon, grid_lat),
                        method="linear", fill_value=np.nan)

    if dim_tiempo is not None:
        n_pasos = lluvia_sf.sizes[dim_tiempo]
        print(f"Procesando {n_pasos} pasos temporales...")
        capas = [interpolar_capa(lluvia_sf.isel({dim_tiempo: i}).values)
                 for i in range(n_pasos)]
        acumulado = np.nansum(np.array(capas), axis=0)
    else:
        acumulado = interpolar_capa(lluvia_sf.values)

    print(f"Max: {np.nanmax(acumulado):.2f} mm | "
          f"Media: {np.nanmean(acumulado):.2f} mm")

    # ---------- 4. Reproyección y GeoTIFF temporal ----------
    lluvia_regular = xr.DataArray(
        acumulado,
        dims=["latitude", "longitude"],
        coords={"latitude": lat_reg, "longitude": lon_reg},
        name="PP",
        attrs={"units": "mm", "long_name": "Precipitacion acumulada 72h"},
    )
    lluvia_regular = lluvia_regular.rio.write_crs("EPSG:4326")
    lluvia_regular = lluvia_regular.rio.set_spatial_dims(
        x_dim="longitude", y_dim="latitude", inplace=True
    )
    lluvia_5347 = lluvia_regular.rio.reproject("EPSG:5347")
    lluvia_5347 = lluvia_5347.rio.write_nodata(np.nan)
    lluvia_5347.rio.to_raster(archivo_tif, nodata=np.nan)
    print(f"GeoTIFF temporal: {archivo_tif}")

    # ---------- 5. Convertir GeoTIFF flotante a 8 bits y generar teselas ----------
    if os.path.exists(DIR_TESELAS):
        subprocess.run(["rm", "-rf", DIR_TESELAS], check=True)

    # Convertir el GeoTIFF flotante a 8 bits con escala 0-255
    # para que gdal2tiles pueda generar PNG.
    archivo_vrt = os.path.join(tmp, "pronostico_8bit.vrt")

    # Rango de escala: 0 mm a MAX_MM. Ajusta MAX_MM si querés más detalle
    # en el rango bajo (por ejemplo, 100 mm) o más rango (por ejemplo, 300 mm).
    MAX_MM = 150.0

    print(f"Convirtiendo a 8 bits (escala 0-{MAX_MM} mm)...")
    subprocess.run([
        "gdal_translate",
        "-of", "VRT",
        "-ot", "Byte",
        "-scale", "0", str(MAX_MM), "0", "255",
        archivo_tif,
        archivo_vrt,
    ], check=True)

    print(f"Generando teselas zoom {ZOOM_MIN}-{ZOOM_MAX}...")
    subprocess.run([
        "gdal2tiles.py",
        "-z", f"{ZOOM_MIN}-{ZOOM_MAX}",
        "-w", "none",
        "-p", "mercator",
        "--processes", "4",
        archivo_vrt,
        DIR_TESELAS,
    ], check=True)
    
    # ---------- 6. Metadata (persistente) ----------
    os.makedirs(DIR_METADATA, exist_ok=True)
    metadata = {
        "fecha_emision": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "corrida_wrf": f"{anio}-{mes}-{dia} 12 UTC",
        "variable": "Precipitacion acumulada 72 h",
        "unidad": "mm",
        "bounds": [[LAT_MIN, LON_MIN], [LAT_MAX, LON_MAX]],
        "zoom_min": ZOOM_MIN,
        "zoom_max": ZOOM_MAX,
        "max_mm": float(np.nanmax(acumulado))
                  if not np.all(np.isnan(acumulado)) else 0,
    }
    with open(os.path.join(DIR_METADATA, "metadata.json"),
              "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    print(f"Metadata: {DIR_METADATA}/metadata.json")
    ds.close()

print("Proceso completo. Solo teselas y metadata quedan en el repo.")
