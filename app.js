/* ============================================================
   MAPA DE RIESGO Y PRONÓSTICO - SANTA FE
   Lógica de visualización: panel desplegable, una capa
   exclusiva a la vez + rutas superponibles.
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
window.map = L.map('map').setView(CENTRO_INICIAL, ZOOM_INICIAL);

L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '© OpenStreetMap'
}).addTo(window.map);

// Contenedor único de leyendas (Arriba a la izquierda)
const contLeyendas = L.control({ position: 'topleft' });
contLeyendas.onAdd = function () {
  const div = L.DomUtil.create('div', 'contenedor-leyendas');
  return div;
};
contLeyendas.addTo(window.map);


// ============================================================
// GESTIÓN DE CAPAS EXCLUSIVAS
// ============================================================
// Registro de capas exclusivas (una activa a la vez)
const capasExclusivas = {
  distritos:       { layer: null, leyenda: null, tipo: 'riesgo' },
  total:           { layer: null, leyenda: null, tipo: 'pron' },
  dia1:            { layer: null, leyenda: null, tipo: 'pron' },
  dia2:            { layer: null, leyenda: null, tipo: 'pron' },
  dia3:            { layer: null, leyenda: null, tipo: 'pron' },
  'chirps-anual':  { layer: null, leyenda: null, tipo: 'chirps' },
  'chirps-mensual':{ layer: null, leyenda: null, tipo: 'chirps' }
};

let capaActiva = null;

function ocultarTodasLasLeyendas() {
  const contenedor = document.querySelector('.contenedor-leyendas');
  if (!contenedor) return;
  // Solo quitamos las leyendas de capas exclusivas, la de rutas vive en otro control
  Object.keys(capasExclusivas).forEach(function (k) {
    const l = capasExclusivas[k].leyenda;
    if (l && contenedor.contains(l)) contenedor.removeChild(l);
  });
}

function mostrarLeyendaDe(nombre) {
  const contenedor = document.querySelector('.contenedor-leyendas');
  const l = capasExclusivas[nombre] && capasExclusivas[nombre].leyenda;
  if (contenedor && l && !contenedor.contains(l)) contenedor.appendChild(l);
}

function activarCapaExclusiva(nombre) {
  if (capaActiva === nombre) return;

  // 1. Desactivar la anterior
  if (capaActiva) {
    const prev = capasExclusivas[capaActiva];
    if (prev.layer) {
      if (prev.tipo === 'chirps' && window.chirps) {
        window.chirps.desactivar(capaActiva);
      } else if (window.map.hasLayer(prev.layer)) {
        window.map.removeLayer(prev.layer);
      }
    }
    if (prev.tipo === 'chirps' && window.chirps) window.chirps.ocultarLeyenda();
  }

  capaActiva = nombre;
  const nueva = capasExclusivas[nombre];
  if (!nueva) return;

  // 2. Activar la nueva
  if (nueva.tipo === 'chirps') {
    if (window.chirps) {
      window.chirps.activar(nombre);
      window.chirps.mostrarLeyenda(nombre === 'chirps-anual' ? 'anual' : 'mensual');
    }
    return;
  }

  if (nueva.layer) {
    if (!window.map.hasLayer(nueva.layer)) nueva.layer.addTo(window.map);
    if (nueva.layer.bringToFront) nueva.layer.bringToFront();
  }

  // 3. Leyenda
  ocultarTodasLasLeyendas();
  mostrarLeyendaDe(nombre);
}

// Enganche de los radios (una sola capa exclusiva)
document.querySelectorAll('input[name="capa-exclusiva"]').forEach(function (radio) {
  radio.addEventListener('change', function () {
    if (radio.checked) activarCapaExclusiva(radio.value);
  });
});


// ============================================================
// 1. CAPA DE DISTRITOS (RIESGO)
// ============================================================
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

fetch('datos/riesgo/distritos_mediana.geojson')
  .then(r => r.json())
  .then(data => {
    const capa = L.geoJSON(data, { style: estiloDistrito, onEachFeature: onEachDistrito });
    capasExclusivas.distritos.layer  = capa;
    capasExclusivas.distritos.leyenda = crearLeyendaRiesgoHTML();

    document.getElementById('chk-distritos').disabled = false;
    // Activar por defecto
    document.getElementById('chk-distritos').checked = true;
    activarCapaExclusiva('distritos');
  })
  .catch(err => {
    console.error('Error cargando distritos:', err);
    document.getElementById('chk-distritos').disabled = true;
  });


// ============================================================
// 2. CAPA DE PRONÓSTICO
// ============================================================
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

    capasExclusivas.total.layer = crearCapaPronostico('total', meta, bounds);
    capasExclusivas.dia1.layer  = crearCapaPronostico('dia1',  meta, bounds);
    capasExclusivas.dia2.layer  = crearCapaPronostico('dia2',  meta, bounds);
    capasExclusivas.dia3.layer  = crearCapaPronostico('dia3',  meta, bounds);

    divLeyendaPron = crearLeyendaPronHTML(meta);
    capasExclusivas.total.leyenda = divLeyendaPron;
    // Las subcapas de pronóstico comparten la misma leyenda
    capasExclusivas.dia1.leyenda = divLeyendaPron;
    capasExclusivas.dia2.leyenda = divLeyendaPron;
    capasExclusivas.dia3.leyenda = divLeyendaPron;

    ['total', 'dia1', 'dia2', 'dia3'].forEach(nombre => {
      const chk = document.getElementById('chk-' + nombre);
      if (chk) chk.disabled = false;
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


// ============================================================
// 3. BOTÓN ÚNICO DE CAPAS
// ============================================================
(function () {
  const btnCapas = document.getElementById('btn-capas');
  const panel = document.getElementById('panel');
  if (!btnCapas || !panel) return;

  btnCapas.addEventListener('click', function () {
    const abierto = !panel.classList.contains('panel-oculto');
    if (abierto) {
      panel.classList.add('panel-oculto');
      btnCapas.setAttribute('aria-expanded', 'false');
    } else {
      panel.classList.remove('panel-oculto');
      btnCapas.setAttribute('aria-expanded', 'true');
    }
  });

  // Cerrar al hacer clic fuera
  document.addEventListener('click', function (e) {
    if (panel.classList.contains('panel-oculto')) return;
    if (panel.contains(e.target)) return;
    if (e.target === btnCapas || btnCapas.contains(e.target)) return;
    panel.classList.add('panel-oculto');
    btnCapas.setAttribute('aria-expanded', 'false');
  });
// ============================================================
// 4. INICIALIZAR CHIRPS
// ============================================================
if (window.chirps && typeof window.chirps.init === 'function') {
  window.chirps.init(window.map);
}
})();
