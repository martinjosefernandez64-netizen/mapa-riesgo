# scripts/generar_chirps.py
import os
import subprocess
import datetime
from dateutil.relativedelta import relativedelta
import numpy as np
import rasterio
from rasterio.merge import merge
from rasterio.mask import mask
import geopandas as gpd
import requests

# ========== 配置 ==========
BASE_URL = "https://data.chc.ucsb.edu/products/CHIRPS/v3.0/monthly/global/tifs/"
GEOJSON_SANTA_FE = "datos/santa_fe.geojson"
TEMP_DIR = "temp_chirps"
TILES_DIR = "tiles_chirps"
NODATA_VALUE = -9999
# ==========================

os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(f"{TILES_DIR}/anual", exist_ok=True)
os.makedirs(f"{TILES_DIR}/mensual", exist_ok=True)

def descargar_mes(year, month):
    """Descarga el GeoTIFF mensual de CHIRPS v3. Retorna la ruta local."""
    filename = f"chirps-v3.0.{year}.{month:02d}.tif"
    url = f"{BASE_URL}{filename}"
    local_path = os.path.join(TEMP_DIR, filename)
    
    if os.path.exists(local_path):
        print(f"  Ya existe: {filename}")
        return local_path
    
    print(f"  Descargando {url} ...")
    r = requests.get(url, stream=True, timeout=120)
    if r.status_code != 200:
        raise Exception(f"Error al descargar {url}: HTTP {r.status_code}")
    
    with open(local_path, 'wb') as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)
    print(f"  Descargado: {filename} ({os.path.getsize(local_path)/1e6:.1f} MB)")
    return local_path

def recortar_a_santa_fe(tif_path, output_path):
    """Recorta el GeoTIFF al polígono de Santa Fe y convierte -9999 a NaN."""
    gdf = gpd.read_file(GEOJSON_SANTA_FE)
    geom = [gdf.geometry.unary_union]
    
    with rasterio.open(tif_path) as src:
        # Recortar
        out_image, out_transform = mask(src, geom, crop=True, nodata=NODATA_VALUE)
        out_meta = src.meta.copy()
        out_meta.update({
            "driver": "GTiff",
            "height": out_image.shape[1],
            "width": out_image.shape[2],
            "transform": out_transform,
            "nodata": np.nan  # 声明为 NaN
        })
        
        # Convertir -9999 a NaN
        out_image = out_image.astype(np.float32)
        out_image[out_image == NODATA_VALUE] = np.nan
        
        with rasterio.open(output_path, "w", **out_meta) as dest:
            dest.write(out_image)
    
    print(f"  Recortado: {output_path}")
    return output_path

def sumar_12_meses(lista_tifs, output_path):
    """Suma píxel a píxel los 12 GeoTIFFs mensuales recortados."""
    print(f"  Sumando {len(lista_tifs)} meses...")
    
    # 使用 rasterio.merge 的 sum 模式，或手动累加
    # 这里采用手动累加，更可控
    with rasterio.open(lista_tifs[0]) as src0:
        meta = src0.meta.copy()
        acumulado = src0.read(1).astype(np.float64)
        # NaN 参与加法会传播 NaN，这正是我们想要的（如果某月缺失，则累计为 NaN）
    
    for tif in lista_tifs[1:]:
        with rasterio.open(tif) as src:
            data = src.read(1).astype(np.float64)
            acumulado = acumulado + data  # NaN + x = NaN
    
    # 写出
    meta.update(dtype='float32', nodata=np.nan)
    with rasterio.open(output_path, 'w', **meta) as dest:
        dest.write(acumulado.astype(np.float32))
    
    print(f"  Suma completada: {output_path}")
    return output_path

def calcular_cuantiles(tif_path, n_clases=5):
    """计算有效像素的 5 个分位数（20%, 40%, 60%, 80%）。"""
    with rasterio.open(tif_path) as src:
        data = src.read(1)
        valid = data[~np.isnan(data) & (data != NODATA_VALUE)]
    
    if len(valid) == 0:
        raise Exception("No hay píxeles válidos para calcular cuantiles")
    
    cuantiles = np.percentile(valid, [20, 40, 60, 80])
    print(f"  Cuantiles (20/40/60/80): {cuantiles}")
    print(f"  Rango: {valid.min():.1f} – {valid.max():.1f} mm")
    return cuantiles

def generar_teselas(tif_path, output_dir):
    """使用 gdal2tiles 生成 XYZ 瓦片。"""
    # 先确保输出目录为空（避免旧瓦片残留）
    if os.path.exists(output_dir):
        subprocess.run(["rm", "-rf", output_dir])
    os.makedirs(output_dir, exist_ok=True)
    
    cmd = [
        "gdal2tiles.py",
        "--xyz",           # Leaflet 需要的 XYZ 方案
        "--zoom=5-10",
        "-w", "none",      # 不生成 Google Maps 兼容的 HTML
        "-r", "bilinear",
        tif_path,
        output_dir
    ]
    print(f"  Ejecutando: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)
    print(f"  Teselas generadas en {output_dir}")

def main():
    # 1. 确定月份范围
    # 最后完整月份 = 上个月（因为本月数据未出）
    hoy = datetime.date.today()
    primer_dia_mes_actual = hoy.replace(day=1)
    ultimo_mes_completo = primer_dia_mes_actual - datetime.timedelta(days=1)
    # 例：今天 2026-10-29 → ultimo_mes_completo = 2026-09-30 → 月份 2026-09
    
    print(f"Último mes completo: {ultimo_mes_completo.year}-{ultimo_mes_completo.month:02d}")
    
    # 2. 最近一个月（用于"último mes"图层）
    tif_mensual = descargar_mes(ultimo_mes_completo.year, ultimo_mes_completo.month)
    tif_mensual_rec = recortar_a_santa_fe(tif_mensual, f"{TEMP_DIR}/mensual_rec.tif")
    
    # 3. 最近 12 个月（用于"anual"图层）
    lista_12 = []
    for i in range(12):
        fecha = ultimo_mes_completo - relativedelta(months=i)
        tif = descargar_mes(fecha.year, fecha.month)
        tif_rec = recortar_a_santa_fe(tif, f"{TEMP_DIR}/mes_{fecha.year}_{fecha.month:02d}_rec.tif")
        lista_12.append(tif_rec)
    
    tif_anual = sumar_12_meses(lista_12, f"{TEMP_DIR}/anual_12m.tif")
    
    # 4. 计算分位数（用于生成图例配置）
    print("\n--- Cuantiles del acumulado anual (12 meses) ---")
    cuantiles_anual = calcular_cuantiles(tif_anual)
    print("\n--- Cuantiles del último mes ---")
    cuantiles_mensual = calcular_cuantiles(tif_mensual_rec)
    
    # 5. 生成瓦片
    print("\n--- Generando teselas del acumulado anual ---")
    generar_teselas(tif_anual, f"{TILES_DIR}/anual")
    
    print("\n--- Generando teselas del último mes ---")
    generar_teselas(tif_mensual_rec, f"{TILES_DIR}/mensual")
    
    # 6. 输出分位数供前端使用（可写入 JSON 文件）
    import json
    metadata = {
        "anual": {
            "cuantiles": [float(x) for x in cuantiles_anual],
            "rango": "últimos 12 meses (sin mes en curso)",
            "fecha_fin": f"{ultimo_mes_completo.year}-{ultimo_mes_completo.month:02d}"
        },
        "mensual": {
            "cuantiles": [float(x) for x in cuantiles_mensual],
            "rango": f"{ultimo_mes_completo.year}-{ultimo_mes_completo.month:02d}"
        }
    }
    with open("datos/chirps_metadata.json", "w") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)
    
    print("\n✅ Proceso completado. Metadata guardada en datos/chirps_metadata.json")

if __name__ == "__main__":
    main()
