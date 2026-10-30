# Mapa de Riesgo y Pronóstico - Santa Fe

Visor web interactivo desarrollado con Leaflet para la provincia de Santa Fe. Permite visualizar de forma interactiva información geoespacial crítica para el monitoreo agropecuario y de riesgo.

## Capas de Información

El visor gestiona las capas mediante un panel desplegable, permitiendo seleccionar una capa de análisis a la vez, con la posibilidad de superponer la red vial en cualquier momento.

1. **Nivel de Riesgo por Distrito:**
   - Muestra la clasificación de riesgo (1 a 5) de los 365 distritos de la provincia.
   - El cálculo se basa en la superficie con riesgo alto y crítico.
   - Al hacer clic en un distrito, se despliega un popup con información detallada y una imagen satelital del ráster de riesgo.

2. **Pronóstico de Precipitación (WRF-SMN):**
   - Precipitación acumulada pronosticada por el modelo WRF-SMN (resolución 4 km).
   - Incluye 4 subcapas: Total 72h, Día 1 (0-24h), Día 2 (24-48h) y Día 3 (48-72h).
   - Se actualiza automáticamente dos veces al día mediante GitHub Actions.

3. **Precipitación Acumulada (CHIRPS v3.0) - *NUEVO*:**
   - **Últimos 12 meses:** Acumulado móvil de los últimos 12 meses completos (sin contar el mes en curso).
   - **Último mes:** Acumulado del último mes completo disponible.
   - Los datos se clasifican en 5 clases utilizando cuantiles (20/40/60/80) calculados dinámicamente para la provincia.
   - Se actualiza automáticamente el día 25 de cada mes mediante GitHub Actions.

4. **Red Vial Provincial:**
   - Trazado de rutas provinciales clasificadas visualmente por tipo de calzada (pavimentado, mejorado, natural).
   - Capa superponible que puede activarse junto a cualquiera de las capas de análisis.

## Estructura del Repositorio

```text
mapa-riesgo/
├── .github/workflows/
│   ├── actualizar_pronostico.yml  # Workflow de GitHub Actions (WRF)
│   └── actualizar_chirps.yml      # Workflow de GitHub Actions (CHIRPS)
├── datos/
│   ├── santa_fe.geojson           # Polígono de la provincia
│   ├── chirps_metadata.json       # Metadata de CHIRPS (cuantiles y fechas)
│   ├── pronostico/
│   │   └── metadata.json          # Metadata del pronóstico vigente
│   ├── riesgo/
│   │   └── distritos_mediana.geojson
│   └── rutas/
│       └── rutas.geojson
├── imagenes/                      # 365 imágenes (una por distrito)
├── scripts/
│   ├── generar_pronostico.py      # Pipeline de pronóstico WRF
│   └── generar_chirps.py          # Pipeline de precipitación CHIRPS
├── tiles_chirps/                  # Teselas de CHIRPS (anual y mensual)
├── tiles_pronostico/              # Teselas del pronóstico WRF
├── index.html
├── app.js
├── chirps.js
├── rutas.js
├── style.css
└── README.md

Actualización de Datos
Pronóstico WRF: Se actualiza automáticamente dos veces al día (04:00 y 15:00 ART).

CHIRPS: Se actualiza automáticamente el día 25 de cada mes (para asegurar la disponibilidad del producto final del mes anterior).

Ejecución Manual de Scripts
Si necesitas regenerar los datos localmente:
pip install -r requirements.txt
python scripts/generar_pronostico.py
python scripts/generar_chirps.py

Tecnologías Utilizadas
Leaflet: Motor de mapas interactivos.
GDAL / Rasterio / RioXarray: Procesamiento de datos geoespaciales y generación de teselas.
GitHub Actions: Automatización de pipelines de datos.
CHIRPS (Climate Hazards Center): Fuente de datos de precipitación histórica.
WRF-SMN (Servicio Meteorológico Nacional): Fuente de datos de pronóstico.
