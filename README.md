# Mapa de Riesgo y Pronóstico - Santa Fe

Visor web interactivo desarrollado con Leaflet para la provincia de Santa Fe. Permite visualizar tres capas de información geoespacial de forma independiente:

1. **Nivel de riesgo por distrito** (365 distritos).
2. **Pronóstico de precipitación acumulada** (WRF-SMN).
3. **Red vial provincial** (rutas).

## Estructura del repositorio

```text
mapa-riesgo/
├── .github/workflows/
│   └── actualizar_pronostico.yml  # Workflow de GitHub Actions
├── datos/
│   ├── santa_fe.geojson           # Polígono de la provincia
│   ├── pronostico/
│   │   └── metadata.json          # Metadata del pronóstico vigente
│   ├── riesgo/
│   │   └── distritos_mediana.geojson # Distritos con nivel de riesgo
│   └── rutas/
│       └── rutas.geojson          # Trazado de rutas provinciales
├── imagenes/
│   └── {DISTRITO}.jpg             # 365 imágenes (una por distrito)
├── scripts/
│   └── generar_pronostico.py      # Pipeline de pronóstico
├── tiles_pronostico/
│   ├── total/{z}/{x}/{y}.png      # Teselas acumulado 72h
│   ├── dia1/{z}/{x}/{y}.png       # Teselas día 1 (0-24h)
│   ├── dia2/{z}/{x}/{y}.png       # Teselas día 2 (24-48h)
│   └── dia3/{z}/{x}/{y}.png       # Teselas día 3 (48-72h)
├── index.html                     # Estructura del visor
├── app.js                         # Lógica de Leaflet (Riesgo y Pronóstico)
├── rutas.js                       # Lógica de Leaflet (Red vial)
├── style.css                      # Estilos del visor
├── requirements.txt
└── README.md
Capa 1: Nivel de riesgo por distrito
Descripción
Cada uno de los 365 distritos (municipios y comunas) de Santa Fe tiene asignada una clase de riesgo (1 a 5) calculada a partir de la superficie con riesgo alto y crítico dentro de cada distrito.

Campos del GeoJSON distritos_mediana.geojson
Campo	Tipo	Descripción
DISTRITO	String	Código único de 4 caracteres (ej. 0727)
NOMBRE1	String	Nombre del distrito
riesgo_median	Double	Mediana del riesgo (escala 1–5)
riesgo_ponderado	Double	Promedio ponderado por superficie (1.0–5.0)
pct_n4_n5	Double	Porcentaje de superficie con riesgo alto + crítico
riesgo_alto_clase	Integer	Clase de riesgo (1–5)
ha	Double	Superficie total del distrito (hectáreas)
b12_ha	Double	Superficie con riesgo muy bajo + bajo (ha)
n3_ha	Double	Superficie con riesgo moderado (ha)
n4_ha	Double	Superficie con riesgo alto (ha)
n5_ha	Double	Superficie con riesgo crítico (ha)
Escala de riesgo_alto_clase
Basada en pct_n4_n5 (porcentaje de superficie con riesgo alto o crítico):

Clase	Etiqueta	Rango de pct_n4_n5	Color
1	Riesgo Muy Bajo	0%	#d9d9d9
2	Riesgo Bajo / Monitoreo	0 – 0.05%	#fdf2c6
3	Riesgo Moderado	0.05 – 0.5%	#e89925
4	Riesgo Alto	0.5 – 2%	#c14a1c
5	Riesgo Crítico	> 2%	#8b1e1e
Actualización
La capa de riesgo no se actualiza automáticamente. Se regenera manualmente cuando cambia el ráster de riesgo fuente (habitualmente una vez por mes después del día 10):

En QGIS, cargar distritos_simp y el ráster de riesgo del mes.

Ejecutar el script Poligonos.py → genera distritos_mediana.geojson.

Ejecutar el script imagenes.py → genera las 365 imágenes.

Subir a GitHub: distritos_mediana.geojson a datos/riesgo/ y las imágenes a imagenes/.

Capa 2: Pronóstico de precipitación
Descripción
Precipitación acumulada según el modelo WRF-SMN (Servicio Meteorológico Nacional), recortada a la provincia de Santa Fe y publicada como 4 capas de teselas XYZ:

Total 72h (suma de los 3 días).

Día 1 (0–24h).

Día 2 (24–48h).

Día 3 (48–72h).

Fuente de datos
Modelo: WRF-SMN (WRF Deterministic, resolución 4 km).

Bucket público: s3://smn-ar-wrf/ (sin credenciales).

Frecuencia: dos corridas diarias (00 UTC y 12 UTC).

Variable: PP (precipitación acumulada).

Actualización automática
El workflow .github/workflows/actualizar_pronostico.yml corre en dos horarios:

04:00 ART (07:00 UTC) — corrida 00 UTC del día anterior.

15:00 ART (18:00 UTC) — corrida 12 UTC del día.

También se puede disparar manualmente desde la pestaña Actions del repositorio (workflow_dispatch).

Metadata del pronóstico
El archivo datos/pronostico/metadata.json contiene:

fecha_emision: fecha y hora ISO 8601 UTC.

corrida_wrf: descripción legible de la corrida.

bounds: extensión geográfica del ráster.

zoom_max: nivel máximo de zoom de las teselas generadas.

capas: objeto con las 4 subcapas (total, dia1, dia2, dia3), indicando su label y max_mm respectivo.

max_mm: máximo de precipitación total en 72h dentro del polígono.

escala: 10 rangos de precipitación con colores y etiquetas.

Capa 3: Red vial (Rutas)
Descripción
Capa vectorial que muestra el trazado de las rutas provinciales, clasificadas visualmente según su tipo de calzada.

Estilos
Pavimentado / Concesionado: Línea continua gruesa.

Mejorado / En ciudad / En construcción: Línea discontinua.

Calzada natural: Línea punteada fina.

Incluye un "halo" blanco debajo de cada línea para mejorar la visibilidad sobre el mapa base y sobre la capa de riesgo.

Cómo usar el visor
Disposición de las leyendas
Para evitar que se superpongan con el panel de capas (esquina superior derecha), las leyendas se han distribuido de la siguiente manera:

Arriba a la izquierda: Leyenda de Nivel de riesgo y Leyenda de Precipitación (se apilan verticalmente según qué capas estén activas).

Abajo a la izquierda: Leyenda de Rutas.

Arriba a la derecha: Panel de control de capas y aviso de vigencia.

Interacción
Clic en un distrito: Abre un popup con su nombre, la imagen satelital del ráster, datos de riesgo y superficies por clase.

Clic en la imagen del popup: Abre la imagen en tamaño completo en una nueva pestaña.

Hover sobre un distrito: Resalta el borde.

Clic en una ruta: Muestra el nombre, jurisdicción, clase y observaciones.

Ejecutar el pipeline localmente
Requisitos
Python 3.10+

GDAL 3.6+

Dependencias de requirements.txt

Pronóstico
bash
pip install -r requirements.txt
python scripts/generar_pronostico.py
El script descargará los datos del bucket de SMN, generará las 4 capas de teselas en tiles_pronostico/ y actualizará metadata.json.
