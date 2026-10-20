/* ============================================================
   MAPA DE RIESGO Y PRONÓSTICO - SANTA FE
   ============================================================ */

const PNG_TRANSPARENTE = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=';
const CENTRO_INICIAL = [-31.5, -60.5];
const ZOOM_INICIAL = 7;
const HORAS_VIGENCIA = 30;

const CLASES_RIESGO = [
  { clase: 1, label: 'Riesgo Muy Bajo',         color: '#d9d9d9' },
  { clase: 2, label: 'Riesgo Bajo / Monitoreo', color: '#fdf2c6' },
  { clase: 3, label: 'Riesgo Moderado',         color: '#e89925' },
  { clase: 4, label: 'Riesgo Alto',             color: '#c14a1c' },
  { clase: 5, label: 'Riesgo Crítico',          color: '#8b1e1e' }
];

const ETIQUETAS_MEDIANA = { 1: 'Muy Bajo', 2: 'Bajo / Monitoreo', 3: 'Moderado', 4: 'Alto', 5: 'Crítico' };

function colorDeClase(clase) {
  const c = CLASES_RIESGO.find(x => x.clase === clase);
  return c ? c.color : '#cccccc';
}

function formatearNumero(n, decimales) {
  if (n === null || n === undefined) return '0';
  return Number(n).toLocaleString('es-AR', { minimumFractionDigits: decimales || 0, maximumFractionDigits: decimales || 0 });
}

// ---------- Mapa ----------
// IMPORTANTE: Lo asignamos a window para que rutas.js pueda acceder a él
window.map = L.map('map').setView(CENTRO_INICIAL, ZOOM_INICIAL);

L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '© OpenStreetMap'
}).addTo(window.map);

// Contenedor de leyendas (esquina inferior derecha)
const contLeyendas = L.control({ position: 'bottomright' });
contLeyendas.onAdd = function () {
  const div = L.DomUtil.create('div', 'contenedor-leyendas');
  return div;
};
contLeyendas.addTo(window.map);


// ============================================================
// 1. CAPA DE DISTRITOS (RIESGO)
// ============================================================
let capaDistritos = null;
let divLeyendaRiesgo = null;

function crearLeyendaRiesgoHTML() {
  const div = L.DomUtil.create('div', 'leyenda-caja');
  let html = '<div class="leyenda-titulo">Nivel de riesgo</div>';
  CLASES_RIESGO.slice().reverse().forEach(function (item) {
    html += '<div class="leyenda-item">' +
            '<span class="leyenda-color" style="background:' + item.color + ';"></span>' +
            '<span>' + item.label + '</span></div>';
  });
  html += '<div class="leyenda-pie">Clasificación por superficie con riesgo alto y crítico</div>';
  div.innerHTML = html;
  return div;
}

function estiloDistrito(feature) {
  const clase = feature.properties.riesgo_alto_clase || 1;
  return {
    fillColor: colorDeClase(clase),
    fillOpacity: 0.5,
    color: '#333333',
    weight: 0.6,
    opacity: 0.8
  };
}

function popupDistrito(feature) {
  const p = feature.properties;
  const urlImagen = 'imagenes/' + p.DISTRITO + '.jpg';
  let html = '<div class="popup-distrito">';
  html += '<h3>' + p.NOMBRE1 + '</h3>';
  html += '<a href="' + urlImagen + '" target="_blank" rel="noopener">' +
          '<img class="popup-imagen" src="' + urlImagen + '" alt="Mapa" loading="lazy"></a>';
  html += '<div class="popup-datos">';
  html += '<div class="linea"><strong>Riesgo mediano:</strong> ' + (ETIQUETAS_MEDIANA[p.riesgo_median] || p.riesgo_median) + '</div>';
  html += '<div class="linea"><strong>Riesgo ponderado:</strong> ' + Number(p.riesgo_ponderado).toFixed(2) + '</div>';
  html += '<div class="linea"><strong>Superficie en riesgo alto+crítico:</strong> ' + Number(p.pct_n4_n5).toFixed(2) + '%</div>';
  html += '</div><div class="popup-superficies">';
  const filas = [
    { clase: 1, etiqueta: 'Bajo (1+2)', valor: p.b12_ha },
    { clase: 3, etiqueta: 'Moderado',   valor: p.n3_ha },
    { clase: 4, etiqueta: 'Alto',       valor: p.n4_ha },
    { clase: 5, etiqueta: 'Crítico',    valor: p.n5_ha }
  ];
  filas.forEach(f => {
    html += '<div class="sup-item"><span><span class="sup-color" style="background:' + colorDeClase(f.clase) + ';"></span>' + f.etiqueta + '</span><span class="sup-valor">' + formatearNumero(f.valor, 0) + ' ha</span></div>';
  });
  return html + '</div></div>';
}

function onEachDistrito(feature, layer) {
  layer.bindPopup(popupDistrito(feature), { maxWidth: 340, minWidth: 280 });
  layer.on('mouseover', function () { this.setStyle({ weight: 2, color: '#000000' }); });
  layer.on('mouseout',  function () { this.setStyle({ weight: 0.6, color: '#333333' }); });
}

function aplicarDistritos(mostrar) {
  if (!capaDistritos) return;
  const contenedor = document.querySelector('.contenedor-leyendas');
  if (mostrar) {
    if (!window.map.hasLayer(capaDistritos)) capaDistritos.addTo(window.map);
    if (divLeyendaRiesgo && !contenedor.contains(divLeyendaRiesgo)) {
      contenedor.prepend(divLeyendaRiesgo); // prepend para que quede arriba
    }
    capaDistritos.bringToFront();
  } else {
    if (window.map.hasLayer(capaDistritos)) window.map.removeLayer(capaDistritos);
    if (divLeyendaRiesgo && contenedor.contains(divLeyendaRiesgo)) {
      contenedor.removeChild(divLeyendaRiesgo);
    }
  }
}

fetch('datos/riesgo/distritos_mediana.geojson')
  .then(r => r.json())
  .then(data => {
    capaDistritos = L.geoJSON(data, { style: estiloDistrito, onEachFeature: onEachDistrito });
    divLeyendaRiesgo = crearLeyendaRiesgoHTML();
    
    document.getElementById('chk-distritos').checked = true;
    aplicarDistritos(true);

    document.getElementById('chk-distritos').addEventListener('change', e => {
      aplicarDistritos(e.target.checked);
    });
  })
  .catch(err => {
    console.error('Error cargando distritos:', err);
    document.getElementById('chk-distritos').disabled = true;
  });


// ============================================================
// 2. CAPA DE PRONÓSTICO
// ============================================================
const capasPron = {};
let divLeyendaPron = null;
let metaPron = null;

function crearLeyendaPronHTML(meta) {
  const div = L.DomUtil.create('div', 'leyenda-caja');
  let html = '<div class="leyenda-titulo">Precipitación (mm)</div>';
  meta.escala.slice().reverse().forEach(function (item) {
    html += '<div class="leyenda-item">' +
            '<span class="leyenda-color" style="background:' + item.color + ';"></span>' +
            '<span>' + item.label + '</span></div>';
  });
  html += '<div class="leyenda-pie">Corrida: ' + meta.corrida_wrf + '<br>Máx total 72 h: ' + meta.max_mm.toFixed(1) + ' mm</div>';
  div.innerHTML = html;
  return div;
}

function crearCapaPronostico(nombre, meta, bounds) {
  return L.tileLayer('tiles_pronostico/' + nombre + '/{z}/{x}/{y}.png', {
    opacity: 0.75, tms: false, minZoom: 0,
    maxNativeZoom: meta.zoom_max ?? 11, maxZoom: 18,
    bounds: bounds, errorTileUrl: PNG_TRANSPARENTE,
    attribution: 'WRF-SMN · ' + (meta.capas[nombre]?.label || nombre)
  });
}

function hayPronosticoVisible() {
  return Object.values(capasPron).some(c => window.map.hasLayer(c));
}

function sincronizarLeyendaPron() {
  if (!divLeyendaPron) return;
  const contenedor = document.querySelector('.contenedor-leyendas');
  const visible = hayPronosticoVisible();
  
  if (visible && !contenedor.contains(divLeyendaPron)) {
    contenedor.appendChild(divLeyendaPron); // appendChild para que quede abajo
  } else if (!visible && contenedor.contains(divLeyendaPron)) {
    contenedor.removeChild(divLeyendaPron);
  }
}

function aplicarSubcapa(nombre, mostrar) {
  const capa = capasPron[nombre];
  if (!capa) return;
  if (mostrar && !window.map.hasLayer(capa)) capa.addTo(window.map);
  else if (!mostrar && window.map.hasLayer(capa)) window.map.removeLayer(capa);
  sincronizarLeyendaPron();
}

function actualizarAviso(meta) {
  const emitido = new Date(meta.fecha_emision);
  const vigenteHasta = new Date(emitido.getTime() + 72 * 3600 * 1000);
  const horasDesdeEmision = (new Date() - emitido) / 3600 / 1000;
  const formatoAR = { timeZone: 'America/Argentina/Buenos_Aires', day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' };

  document.getElementById('aviso-emitido').textContent = emitido.toLocaleString('es-AR', formatoAR);
  document.getElementById('aviso-vigencia').textContent = vigenteHasta.toLocaleString('es-AR', formatoAR);
  
  const estado = document.getElementById('aviso-estado');
  if (horasDesdeEmision > HORAS_VIGENCIA) {
    estado.innerHTML = '<span style="color:#c0392b;">Última actualización hace ' + Math.round(horasDesdeEmision) + ' h.</span>';
  } else {
    estado.innerHTML = '<span style="color:#1a7f37;">Actualizado. Máx: ' + meta.max_mm.toFixed(1) + ' mm.</span>';
  }
}

fetch('datos/pronostico/metadata.json')
  .then(r => r.json())
  .then(meta => {
    metaPron = meta;
    if (!meta.fecha_emision) throw new Error('Metadata vacía');

    actualizarAviso(meta);
    const bounds = L.latLngBounds([meta.bounds[0][0], meta.bounds[0][1]], [meta.bounds[1][0], meta.bounds[1][1]]);

    capasPron.total = crearCapaPronostico('total', meta, bounds);
    capasPron.dia1  = crearCapaPronostico('dia1',  meta, bounds);
    capasPron.dia2  = crearCapaPronostico('dia2',  meta, bounds);
    capasPron.dia3  = crearCapaPronostico('dia3',  meta, bounds);
    
    divLeyendaPron = crearLeyendaPronHTML(meta);

    ['total', 'dia1', 'dia2', 'dia3'].forEach(nombre => {
      const idCheck = 'chk-' + (nombre === 'total' ? 'total' : nombre);
      const chk = document.getElementById(idCheck);
      chk.checked = false;
      chk.addEventListener('change', e => aplicarSubcapa(nombre, e.target.checked));
    });
  })
  .catch(err => {
    console.error('Error cargando pronóstico:', err);
    document.getElementById('aviso-vencido').style.display = 'block';
    ['chk-total', 'chk-dia1', 'chk-dia2', 'chk-dia3'].forEach(id => {
      const c = document.getElementById(id);
      if (c) c.disabled = true;
    });
  });
