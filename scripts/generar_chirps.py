# -*- coding: utf-8 -*-
"""
Genera las capas de precipitación acumulada de CHIRPS v3.0 para Santa Fe.

Genera 2 capas:
- mensual: precipitación acumulada del último mes completo.
- anual:   precipitación acumulada de los últimos 12 meses móviles
           (sin contar el mes en curso).

Flujo:
1. Descarga los GeoTIFF mensuales de CHIRPS v3.0 (bucket público de CHC/UCSB).
   Si CHIRPS_CACHE_DIR está definido, cachea los crudos entre ejecuciones.
2. Recorta cada mes al polígono de Santa Fe con rioxarray.clip (mismo
   criterio que generar_pronostico.py: fuera del polígono → -9999).
   Los recortes también se cachean si CHIRPS_CACHE_DIR está definido.
3. Suma los 12 meses para el acumulado anual.
4. Calcula cuantiles (20/40/60/80) solo sobre píxeles válidos dentro
   del polígono, para clasificar en 5 clases.
5. Genera un PNG coloreado con gdaldem color-relief -alpha (nodata
   transparente) y luego las teselas XYZ con gdal2tiles.
6. Escribe datos/chirps_metadata.json con los cuantiles y fechas.

Fuente de datos:
- https://data.chc.ucsb.edu/products/CHIRPS/v3.0/monthly/global/tifs/
- Resolución 0.05°, unidades mm/mes, NoData = -9999.
"""

import os
import sys
import json
import shutil
import logging
import datetime
import subprocess
import tempfile
import time

import numpy as np
import xarray as xr
import rioxarray  # noqa: F401
import rasterio
import geopandas as gpd
import requests
from dateutil.relativedelta import relativedelta

# ============================================================
# LOGGING
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("chirps")

# ============================================================
# CONFIGURACIÓN
# ============================================================
BASE_URL = "https://data.chc.ucsb.edu/products/CHIRPS/v3.0/monthly/global/tifs/"
RUTA_POLIGONO = "datos/santa_fe.geojson"
DIR_TESELAS = "tiles_chirps"
DIR_METADATA = "datos"
ARCHIVO_METADATA = os.path.join(DIR_METADATA, "chirps_metadata.json")

# Directorio de caché persistente entre ejecuciones del workflow.
# Si no está definido, se usa el tmp_dir temporal.
CACHE_DIR = os.environ.get("CHIRPS_CACHE_DIR", "").strip()

NODATA_VALOR = -9999
# CHIRPS tiene 0.05° de resolución (~5.5 km). Zoom 8 ya es más resolución
# de la que los datos tienen; zoom 10 multiplica x16 las teselas sin
# ganancia visual y hace que gdal2tiles se cuelgue.
ZOOM_MIN, ZOOM_MAX = 5, 8
N_MESES_ANUAL = 12

# 5 colores para las 5 clases por cuantiles
COLORES_CLASES = [
    "#ffffcc",  # clase 1 (más seco)
    "#a1dab4",  # clase 2
    "#41b6c4",  # clase 3
    "#2c7fb8",  # clase 4
    "#253494",  # clase 5 (más húmedo)
]


# ============================================================
# FUNCIONES AUXILIARES
# ============================================================
def hex_a_rgb(hex_color):
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def cargar_poligono():
    """Carga y valida el GeoJSON de Santa Fe."""
    if not os.path.exists(RUTA_POLIGONO):
        log.error("No se encontró %s. Se aborta.", RUTA_POLIGONO)
        sys.exit(1)

    gdf = gpd.read_file(RUTA_POLIGONO)
    if gdf.crs is None or gdf.crs.to_epsg() != 4326:
        log.info("  Reproyectando %s a EPSG:4326...", RUTA_POLIGONO)
        gdf = gdf.to_crs(4326)

    if not gdf.geometry.is_valid.all():
        log.info("  Corrigiendo geometrías inválidas con make_valid()...")
        try:
            gdf = gdf.make_valid()
        except AttributeError:
            from shapely.validation import make_valid
            gdf["geometry"] = gdf.geometry.apply(make_valid)

    geom_union = gdf.geometry.union_all()
    if geom_union is None or geom_union.is_empty:
        log.error("La geometría de Santa Fe quedó vacía tras union_all().")
        sys.exit(1)

    log.info("  Polígono de Santa Fe cargado correctamente.")
    return gdf


def descargar_mes(year, month, tmp_dir, max_intentos=3):
    """
    Descarga el GeoTIFF mensual de CHIRPS v3.0. Retorna la ruta local.

    Si CACHE_DIR está definido, usa ese directorio persistente para que
    los archivos sobrevivan entre ejecuciones del workflow. Si no,
    usa tmp_dir (se borra al terminar el script).
    """
    filename = f"chirps-v3.0.{year}.{month:02d}.tif"
    url = f"{BASE_URL}{filename}"

    base_dir = CACHE_DIR if CACHE_DIR else tmp_dir
    os.makedirs(base_dir, exist_ok=True)
    local_path = os.path.join(base_dir, filename)

    if os.path.exists(local_path) and os.path.getsize(local_path) > 1_000_000:
        log.info("  Ya existe en caché: %s", filename)
        return local_path

    for intento in range(max_intentos):
        try:
            log.info("  Descargando %s (intento %d)...", url, intento + 1)
            r = requests.get(url, stream=True, timeout=300)
            if r.status_code != 200:
                raise RuntimeError(f"HTTP {r.status_code}")
            with open(local_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
            if os.path.getsize(local_path) > 1_000_000:
                log.info("    OK (%.1f MB)", os.path.getsize(local_path) / 1e6)
                return local_path
            os.remove(local_path)
        except Exception as e:
            log.warning("    Intento %d falló: %s", intento + 1, e)
            if os.path.exists(local_path):
                os.remove(local_path)
            time.sleep(2 * (intento + 1))

    raise RuntimeError(f"No se pudo descargar {url}")


def recortar_a_santa_fe(tif_path, output_path, gdf):
    """
    Recorta el GeoTIFF de CHIRPS al polígono de Santa Fe.

    - Píxeles fuera del polígono → -9999 (nodata).
    - Declara nodata=-9999 en el GeoTIFF de salida.
    - Deja el archivo listo para gdaldem color-relief -alpha.
    - Si output_path ya existe y es más reciente que tif_path,
      lo reutiliza (caché de recortes).
    """
    if (os.path.exists(output_path) and
            os.path.getmtime(output_path) >= os.path.getmtime(tif_path)):
        log.info("  Recorte ya en caché: %s", os.path.basename(output_path))
        return output_path

    da = xr.open_dataarray(tif_path, engine="rasterio")

    # Normalizar dimensiones: quitar eje 'band' si existe
    if "band" in da.dims:
        da = da.isel(band=0, drop=True)

    # Asegurar CRS
    if da.rio.crs is None:
        da = da.rio.write_crs("EPSG:4326")

    # Recorte real por polígono (NO solo bbox)
    da_rec = da.rio.clip(
        gdf.geometry.values, gdf.crs, drop=False, invert=False
    )

    # Fuera del polígono queda NaN → rellenar con -9999
    da_rec = da_rec.fillna(NODATA_VALOR)
    da_rec = da_rec.rio.write_nodata(NODATA_VALOR)

    da_rec.rio.to_raster(output_path, nodata=NODATA_VALOR)
    log.info("  Recortado (por polígono): %s", os.path.basename(output_path))
    return output_path


def sumar_meses(lista_tifs, output_path):
    """
    Suma píxel a píxel los GeoTIFFs recortados (para el acumulado anual).

    - Verifica que todas las formas coincidan.
    - NaN / -9999 se propagan: si un mes no tiene dato en un píxel,
      el acumulado tampoco lo tiene (NaN → -9999 al escribir).
    - Escribe con el eje de bandas correcto (1, H, W).
    """
    log.info("  Sumando %d meses...", len(lista_tifs))

    with rasterio.open(lista_tifs[0]) as src0:
        meta = src0.meta.copy()
        shape_ref = (src0.height, src0.width)
        acumulado = src0.read(1).astype(np.float64)
        acumulado[acumulado == NODATA_VALOR] = np.nan

    for tif in lista_tifs[1:]:
        with rasterio.open(tif) as src:
            if (src.height, src.width) != shape_ref:
                raise ValueError(
                    f"Forma inconsistente en {tif}: "
                    f"{(src.height, src.width)} vs {shape_ref}"
                )
            data = src.read(1).astype(np.float64)
            data[data == NODATA_VALOR] = np.nan
            acumulado = acumulado + data  # NaN + x = NaN

    # Escribir con eje de bandas: (1, H, W)
    meta.update(
        dtype="float32",
        nodata=NODATA_VALOR,
        count=1,
    )
    salida = acumulado.astype(np.float32)
    salida[np.isnan(salida)] = NODATA_VALOR

    with rasterio.open(output_path, "w", **meta) as dest:
        dest.write(salida[np.newaxis, :, :])

    log.info("  Suma completada: %s", os.path.basename(output_path))
    return output_path


def calcular_cuantiles(tif_path, n_clases=5):
    """
    Calcula cuantiles (20/40/60/80 para 5 clases) solo sobre píxeles
    válidos dentro del polígono (es decir, distintos de -9999).
    """
    with rasterio.open(tif_path) as src:
        data = src.read(1)

    valid = data[data != NODATA_VALOR]
    if len(valid) == 0:
        raise ValueError("No hay píxeles válidos dentro del polígono de Santa Fe")

    cuantiles = np.percentile(valid, [20, 40, 60, 80])
    log.info("  Cuantiles (20/40/60/80): %s",
             [f"{q:.2f}" for q in cuantiles])
    log.info("  Rango válido: %.1f – %.1f mm", valid.min(), valid.max())
    log.info("  N píxeles válidos: %d", len(valid))
    return cuantiles


def generar_capa_chirps(tif_recortado, cuantiles, output_dir, tmp_dir, nombre):
    """
    Genera teselas coloreadas por cuantiles con transparencia fuera del polígono.

    Sigue el mismo patrón que generar_capa() del pronóstico:
    1. Tabla de paleta: -9999 → (0,0,0,0) + 5 colores en los cortes.
    2. gdaldem color-relief -alpha → PNG con transparencia.
    3. gdal_translate a PNG (más rápido de teselar que GeoTIFF).
    4. gdal2tiles.py sobre el PNG, SIN --processes (evita el cuelgue
       de gdal2tiles en GDAL 3.8.x con --xyz) y con ZOOM_MAX=8.
    """
    # 1. Construir tabla de paleta
    # gdaldem interpreta cada fila como límite inferior del intervalo.
    cortes = [0] + [float(q) for q in cuantiles] + [1e9]  # 6 cortes → 5 clases

    lineas = [f"{NODATA_VALOR} 0 0 0 0"]  # nodata → transparente
    for i in range(5):
        r, g, b = hex_a_rgb(COLORES_CLASES[i])
        lineas.append(f"{cortes[i]} {r} {g} {b} 255")

    tabla = os.path.join(tmp_dir, f"paleta_{nombre}.txt")
    with open(tabla, "w") as f:
        f.write("\n".join(lineas))

    # 2. GeoTIFF coloreado con transparencia
    tif_color = os.path.join(tmp_dir, f"{nombre}_color.tif")
    subprocess.run([
        "gdaldem", "color-relief",
        tif_recortado, tabla, tif_color, "-alpha",
    ], check=True)

    # 3. Convertir a PNG (más rápido para gdal2tiles que leer GeoTIFF)
    png_color = os.path.join(tmp_dir, f"{nombre}_color.png")
    subprocess.run([
        "gdal_translate", "-of", "PNG", tif_color, png_color,
    ], check=True)

    # 4. Teselas (sin --processes, zoom máximo 8)
    if os.path.exists(output_dir):
        shutil.rmtree(output_dir)
    subprocess.run([
        "gdal2tiles.py",
        "-z", f"{ZOOM_MIN}-{ZOOM_MAX}",
        "-w", "none",
        "-p", "mercator",
        "--xyz",
        "-r", "bilinear",
        "--quiet",
        png_color,
        output_dir,
    ], check=True)

    log.info("  Teselas generadas en %s", output_dir)


# ============================================================
# MAIN
# ============================================================
def main():
    log.info("=" * 60)
    log.info("CHIRPS v3.0 — GENERANDO CAPAS PARA SANTA FE")
    log.info("=" * 60)

    if CACHE_DIR:
        log.info("Modo caché persistente: %s", CACHE_DIR)
    else:
        log.info("Modo sin caché persistente (solo tmp)")

    # 1. Cargar polígono
    gdf = cargar_poligono()

    # 2. Determinar rango de meses
    hoy = datetime.date.today()
    primer_dia_mes_actual = hoy.replace(day=1)
    ultimo_mes_completo = primer_dia_mes_actual - datetime.timedelta(days=1)
    log.info("Último mes completo: %04d-%02d",
             ultimo_mes_completo.year, ultimo_mes_completo.month)

    with tempfile.TemporaryDirectory() as tmp:
        # 3. Directorio para recortes: caché persistente si existe
        rec_dir = os.path.join(CACHE_DIR, "recortes") if CACHE_DIR else tmp
        os.makedirs(rec_dir, exist_ok=True)

        # 4. Descargar y recortar los 12 meses (incluye el último)
        log.info("=" * 60)
        log.info("DESCARGANDO Y RECORTANDO LOS %d MESES", N_MESES_ANUAL)
        log.info("=" * 60)

        recortados = []
        for i in range(N_MESES_ANUAL):
            fecha = ultimo_mes_completo - relativedelta(months=i)
            log.info("Mes %02d/%02d: %04d-%02d",
                     i + 1, N_MESES_ANUAL, fecha.year, fecha.month)
            tif = descargar_mes(fecha.year, fecha.month, tmp)
            tif_rec = os.path.join(
                rec_dir, f"mes_{fecha.year}_{fecha.month:02d}_rec.tif"
            )
            recortar_a_santa_fe(tif, tif_rec, gdf)
            recortados.append(tif_rec)

        # 5. Capa mensual = el primer recortado (último mes completo)
        tif_mensual = recortados[0]
        log.info("Capa mensual lista: %s", os.path.basename(tif_mensual))

        # 6. Capa anual = suma de los 12 recortados
        log.info("=" * 60)
        log.info("SUMANDO LOS %d MESES (ACUMULADO ANUAL)", N_MESES_ANUAL)
        log.info("=" * 60)
        tif_anual = os.path.join(tmp, "anual_12m.tif")
        sumar_meses(recortados, tif_anual)

        # 7. Cuantiles
        log.info("=" * 60)
        log.info("CALCULANDO CUANTILES")
        log.info("=" * 60)
        log.info("--- Mensual ---")
        cuantiles_mensual = calcular_cuantiles(tif_mensual)
        log.info("--- Anual (12 meses) ---")
        cuantiles_anual = calcular_cuantiles(tif_anual)

        # 8. Generar teselas
        log.info("=" * 60)
        log.info("GENERANDO TESELAS")
        log.info("=" * 60)
        log.info("--- Mensual ---")
        generar_capa_chirps(
            tif_mensual, cuantiles_mensual,
            os.path.join(DIR_TESELAS, "mensual"),
            tmp, "mensual",
        )
        log.info("--- Anual ---")
        generar_capa_chirps(
            tif_anual, cuantiles_anual,
            os.path.join(DIR_TESELAS, "anual"),
            tmp, "anual",
        )

    # 9. Metadata
    log.info("=" * 60)
    log.info("ESCRIBIENDO METADATA")
    log.info("=" * 60)

    os.makedirs(DIR_METADATA, exist_ok=True)

    fecha_fin_anual = ultimo_mes_completo
    fecha_inicio_anual = ultimo_mes_completo - relativedelta(months=N_MESES_ANUAL - 1)

    metadata = {
        "fecha_generacion": datetime.datetime.now(
            datetime.timezone.utc).isoformat(),
        "fuente": "CHIRPS v3.0 (CHC/UCSB)",
        "resolucion": "0.05°",
        "unidad": "mm",
        "mensual": {
            "rango": f"{ultimo_mes_completo.year}-{ultimo_mes_completo.month:02d}",
            "cuantiles": [float(q) for q in cuantiles_mensual],
            "colores": COLORES_CLASES,
        },
        "anual": {
            "rango": (
                f"{fecha_inicio_anual.year}-{fecha_inicio_anual.month:02d} "
                f"a {fecha_fin_anual.year}-{fecha_fin_anual.month:02d}"
            ),
            "fecha_fin": f"{fecha_fin_anual.year}-{fecha_fin_anual.month:02d}",
            "cuantiles": [float(q) for q in cuantiles_anual],
            "colores": COLORES_CLASES,
        },
    }

    with open(ARCHIVO_METADATA, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    log.info("  Metadata: %s", ARCHIVO_METADATA)
    log.info("=" * 60)
    log.info("PROCESO COMPLETO")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
