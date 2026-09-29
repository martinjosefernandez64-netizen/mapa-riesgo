# Mapa de Riesgo - Santa Fe

Visor interactivo con dos capas independientes sobre la provincia de Santa Fe:

1. **Nivel de riesgo por distrito** — clasificación de municipios y comunas según la superficie con riesgo alto y crítico.
2. **Pronóstico de precipitación acumulada 72 h** — salida del modelo WRF-SMN, actualizada automáticamente dos veces por día.

**Visor publicado:** https://martinjosefernandez64-netizen.github.io/mapa-riesgo/

---

## Estructura del repositorio
mapa-riesgo/
├── .github/workflows/
│ └── actualizar_pronostico.yml Workflow de GitHub Actions
├── datos/
│ ├── santa_fe.geojson Polígono de la provincia
│ ├── pronostico/
│ │ └── metadata.json Metadata del pronóstico vigente
│ └── riesgo/
│ └── distritos_mediana.geojson Distritos con nivel de riesgo
├── imagenes/
│ └── {DISTRITO}.jpg 365 imágenes (una por distrito)
├── scripts/
│ └── generar_pronostico.py Pipeline de pronóstico
├── tiles_pronostico/{z}/{x}/{y}.png Teselas XYZ del pronóstico
├── index.html Estructura del visor
├── app.js Lógica de Leaflet
├── style.css Estilos
├── requirements.txt
└── README.md


---

## Capa de nivel de riesgo por distrito

### Descripción

Cada uno de los **365 distritos** (municipios y comunas) de Santa Fe tiene asignada una clase de riesgo (1 a 5) calculada a partir de la superficie con riesgo alto y crítico dentro de cada distrito.

### Campos del GeoJSON `distritos_mediana.geojson`

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `DISTRITO` | String | Código único de 4 caracteres (ej. `0727`) |
| `NOMBRE1` | String | Nombre del distrito |
| `riesgo_median` | Double | Mediana del riesgo (escala 1–5) |
| `riesgo_ponderado` | Double | Promedio ponderado por superficie (1.0–5.0) |
| `pct_n4_n5` | Double | Porcentaje de superficie con riesgo alto + crítico |
| `riesgo_alto_clase` | Integer | Clase de riesgo (1–5) |
| `ha` | Double | Superficie total del distrito (hectáreas) |
| `b12_ha` | Double | Superficie con riesgo muy bajo + bajo (ha) |
| `n3_ha` | Double | Superficie con riesgo moderado (ha) |
| `n4_ha` | Double | Superficie con riesgo alto (ha) |
| `n5_ha` | Double | Superficie con riesgo crítico (ha) |

### Escala de `riesgo_alto_clase`

La clasificación se basa en `pct_n4_n5` (porcentaje de la superficie del distrito con riesgo alto o crítico):

| Clase | Etiqueta | Rango de `pct_n4_n5` | Color |
|-------|----------|----------------------|-------|
| 1 | Riesgo Muy Bajo | 0% | `#d9d9d9` |
| 2 | Riesgo Bajo / Monitoreo | 0 – 0.05% | `#fdf2c6` |
| 3 | Riesgo Moderado | 0.05 – 0.5% | `#e89925` |
| 4 | Riesgo Alto | 0.5 – 2% | `#c14a1c` |
| 5 | Riesgo Crítico | > 2% | `#8b1e1e` |

Los colores y etiquetas coinciden con los del ráster de riesgo original.

### Imágenes por distrito

Cada distrito tiene una imagen JPG de 1000×1000 px en `imagenes/{DISTRITO}.jpg` que muestra el distrito centrado sobre el ráster de riesgo, con los bordes de todos los distritos superpuestos. La imagen se abre en una nueva pestaña al hacer clic desde el popup del visor.

### Actualización

La capa de riesgo **no se actualiza automáticamente**. Se regenera manualmente cuando cambia el ráster de riesgo fuente (habitualmente una vez por mes después del día 10):

1. En QGIS, cargar `distritos_simp` y el ráster de riesgo del mes.
2. Ejecutar el script `Poligonos.py` → genera `distritos_mediana.geojson`.
3. Ejecutar el script `imagenes.py` → genera las 365 imágenes.
4. Subir a GitHub:
   - `distritos_mediana.geojson` → `datos/riesgo/`
   - Las 365 imágenes → `imagenes/`

---

## Capa de pronóstico de precipitación

### Descripción

Precipitación acumulada a 72 horas según el modelo **WRF-SMN** (Servicio Meteorológico Nacional), recortada a la provincia de Santa Fe y publicada como teselas XYZ.

### Fuente de datos

- **Modelo:** WRF-SMN (WRF Deterministic, resolución 4 km)
- **Bucket público:** `s3://smn-ar-wrf/` (sin credenciales)
- **Frecuencia:** dos corridas diarias (00 UTC y 12 UTC)
- **Variable:** `PP` (precipitación acumulada cada 10 minutos)

### Actualización automática

El workflow `.github/workflows/actualizar_pronostico.yml` corre en dos horarios:

- **04:00 ART** (07:00 UTC) — corrida 00 UTC del día anterior
- **15:00 ART** (18:00 UTC) — corrida 12 UTC del día

También se puede disparar manualmente desde la pestaña **Actions** del repositorio (`workflow_dispatch`).

### Metadata del pronóstico

El archivo `datos/pronostico/metadata.json` contiene:

- `fecha_emision` — fecha y hora ISO 8601 UTC
- `corrida_wrf` — descripción legible de la corrida
- `bounds` — extensión geográfica del ráster
- `max_mm` — máximo de precipitación dentro del polígono de Santa Fe
- `escala` — 10 rangos de precipitación con colores y etiquetas

El visor lee este archivo para mostrar el aviso de vigencia y construir la leyenda dinámicamente.

---

## Cómo usar el visor

### Capas disponibles

- **Nivel de riesgo** (activa por defecto): distritos coloreados según su clase de riesgo, con opacidad al 50%.
- **Pronóstico 72 h** (desactivada por defecto): teselas del pronóstico de precipitación con opacidad al 75%.

Ambas capas se pueden activar y desactivar de forma independiente desde el panel **Capas** (arriba a la derecha).

### Interacción

- **Clic en un distrito:** abre un popup con el nombre, la imagen, los datos de riesgo y las superficies por clase.
- **Clic en la imagen del popup:** abre la imagen en tamaño completo en una nueva pestaña.
- **Hover sobre un distrito:** resalta el borde.

### Leyendas

- **Nivel de riesgo:** se muestra abajo a la derecha cuando la capa de distritos está activa.
- **Precipitación:** se muestra abajo a la derecha cuando la capa de pronóstico está activa.

Si ambas capas están activas, las dos leyendas se apilan en la esquina inferior derecha.

---

## Ejecutar el pipeline localmente

### Requisitos

- Python 3.10+
- GDAL 3.6+
- Las dependencias de `requirements.txt`

### Pronóstico

```bash
pip install -r requirements.txt
python scripts/generar_pronostico.py
