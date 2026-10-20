/* ============================================================
   MAPA DE RIESGO - SANTA FE
   - Capa de distritos con nivel de riesgo (activa por defecto)
   - Capa de pronóstico de precipitación con 4 subcapas:
       total 72h / día 1 / día 2 / día 3
   Las teselas del pronóstico se generan con generar_pronostico.py
   en tiles_pronostico/{capa}/{z}/{x}/{y}.png
   ============================================================ */

// ---------- Constantes ----------
const PNG_TRANSPARENTE =
  'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=';

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

const ETIQUETAS_MEDIANA = {
  1: 'Muy Bajo',
  2: 'Bajo / Monitoreo',
  3: 'Moderado',
  4: 'Alto',
  5: 'Crítico'
};

function colorDeClase(clase) {
  const c = CLASES_RIESGO.find(x => x.clase === clase);
  return c ? c.color : '#cccccc';
}

function formatearNumero(n, decimales) {
  if (n === null || n === undefined) return '0';
  return Number(n).toLocaleString('es-AR', {
    minimumFractionDigits: decimales || 0,
    maximumFractionDigits: decimales || 0
  });
}

// ---------- Mapa ----------
const map = L.map('map').setView(CENTRO_INICIAL, ZOOM_INICIAL);

L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '© OpenStreetMap'
}).addTo(map);

// ---------- Referencias a checkboxes ----------
const chkDistritos = document.getElementById('chk-distritos');
const chkTotal     = document.getElementById('chk-total');
const chkDia1      = document.getElementById('chk-dia1');
const chkDia2      = document.getElementById('chk-dia2');
const chkDia3      = document.getElementById('chk-dia3');

if (!chkDistritos || !chkTotal || !chkDia1 || !chkDia2 || !chkDia3) {
  console.error(
    'Faltan checkboxes en index.html: se esperan ' +
    'chk-distritos, chk-total, chk-dia1, chk-dia2, chk-dia3'
  );
}

// ============================================================
// CAPA DE DISTRITOS (riesgo)
// ============================================================
let capaDistritos = null;
let controlLeyendaRiesgo = null;

function construirLeyendaRiesgo() {
  const leyenda = L.control({ position: 'bottomright' });
  leyenda.onAdd = function () {
    const div = L.DomUtil.create('div', 'leyenda');
    let html = '<div class="leyenda-titulo">Nivel de riesgo</div>';
    CLASES_RIESGO.slice().reverse().forEach(function (item) {
      html += '<div class="leyenda-item">' +
              '<span class="leyenda-color" style="background:' + item.color + ';"></span>' +
              '<span>' + item.label + '</span>' +
              '</div>';
    });
    html += '<div class="leyenda-pie">' +
            'Clasificación por superficie con riesgo alto y crítico' +
            '</div>';
    div.innerHTML = html;
    return div;
  };
  return leyenda;
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
  const codigo = p.DISTRITO;
  const nombre = p.NOMBRE1;
  const mediana = p.riesgo_median;
  const ponderado = p.riesgo_ponderado;
  const pctAlto = p.pct_n4_n5;
  const urlImagen = 'imagenes/' + codigo + '.jpg';

  let html = '<div class="popup-distrito">';
  html += '<h3>' + nombre + '</h3>';
  html += '<a href="' + urlImagen + '" target="_blank" rel="noopener">' +
          '<img class="popup-imagen" src="' + urlImagen + '" ' +
          'alt="Mapa de ' + nombre + '" loading="lazy">' +
          '</a>';

  html += '<div class="popup-datos">';
  html += '<div class="linea"><strong>Riesgo mediano:</strong> ' +
          (ETIQUETAS_MEDIANA[mediana] || mediana) + '</div>';
  html += '<div class="linea"><strong>Riesgo ponderado:</strong> ' +
          Number(ponderado).toFixed(2) + '</div>';
  html += '<div class="linea"><strong>Superficie en riesgo alto+crítico:</strong> ' +
          Number(pctAlto).toFixed(2) + '%</div>';
  html += '</div>';

  html += '<div class="popup-superficies">';
  const filas = [
    { clase: 1, etiqueta: 'Bajo (1+2)', valor: p.b12_ha },
    { clase: 3, etiqueta: 'Moderado',   valor: p.n3_ha },
    { clase: 4, etiqueta: 'Alto',       valor: p.n4_ha },
    { clase: 5, etiqueta: 'Crítico',    valor: p.n5_ha }
  ];
  filas.forEach(function (f) {
    html += '<div class="sup-item">' +
            '<span><span class="sup-color" style="background:' +
            colorDeClase(f.clase) + ';"></span>' + f.etiqueta + '</span>' +
            '<span class="sup-valor">' + formatearNumero(f.valor, 0) + ' ha</span>' +
            '</div>';
  });
  html += '</div></div>';
  return html;
}

function onEachDistrito(feature, layer) {
  layer.bindPopup(popupDistrito(feature), { maxWidth: 340, minWidth: 280 });
  layer.on('mouseover', function () {
    this.setStyle({ weight: 2, color: '#000000' });
  });
  layer.on('mouseout', function () {
    this.setStyle({ weight: 0.6, color: '#333333' });
  });
}

function aplicarDistritos(mostrar) {
  if (!capaDistritos) return;
  if (mostrar) {
    if (!map.hasLayer(capaDistritos)) capaDistritos.addTo(map);
    if (!map.hasLayer(controlLeyendaRiesgo)) controlLeyendaRiesgo.addTo(map);
    capaDistritos.bringToFront();
  } else {
    if (map.hasLayer(capaDistritos)) map.removeLayer(capaDistritos);
    if (map.hasLayer(controlLeyendaRiesgo)) map.removeControl(controlLeyendaRiesgo);
  }
}

fetch('datos/riesgo/distritos_mediana.geojson')
  .then(function (r) {
    if (!r.ok) throw new Error('HTTP ' + r.status + ' al cargar GeoJSON de distritos');
    return r.json();
  })
  .then(function (data) {
    capaDistritos = L.geoJSON(data, {
      style: estiloDistrito,
      onEachFeature: onEachDistrito
    });
    controlLeyendaRiesgo = construirLeyendaRiesgo();

    chkDistritos.checked = true;
    aplicarDistritos(true);

    chkDistritos.addEventListener('change', function (e) {
      aplicarDistritos(e.target.checked);
    });
  })
  .catch(function (err) {
    console.error('Distritos:', err);
    if (chkDistritos) chkDistritos.disabled = true;
  });

// ============================================================
// CAPA DE PRONÓSTICO (4 subcapas)
// ============================================================
const capasPron = {};        // { total, dia1, dia2, dia3 }
let controlLeyendaPron = null;
let metaPron = null;

function construirLeyendaPronostico(meta) {
  const leyenda = L.control({ position: 'bottomright' });
  leyenda.onAdd = function () {
    const div = L.DomUtil.create('div', 'leyenda');
    let html = '<div class="leyenda-titulo">Precipitación (mm)</div>';
    meta.escala.slice().reverse().forEach(function (item) {
      html += '<div class="leyenda-item">' +
              '<span class="leyenda-color" style="background:' + item.color + ';"></span>' +
              '<span>' + item.label + '</span>' +
              '</div>';
    });
    html += '<div class="leyenda-pie">' +
            'Corrida: ' + meta.corrida_wrf + '<br>' +
            'Máx total 72 h: ' + meta.max_mm.toFixed(1) + ' mm' +
            '</div>';
    div.innerHTML = html;
    return div;
  };
  return leyenda;
}

function crearCapaPronostico(nombre, meta, bounds) {
  return L.tileLayer(
    'tiles_pronostico/' + nombre + '/{z}/{x}/{y}.png',
    {
      opacity: 0.75,
      tms: false,
      minZoom: 0,
      maxNativeZoom: meta.zoom_max ?? 11,
      maxZoom: 18,
      bounds: bounds,
      errorTileUrl: PNG_TRANSPARENTE,
      attribution: 'WRF-SMN · ' + (meta.capas[nombre]?.label || nombre)
    }
  );
}

// Devuelve true si al menos una subcapa de pronóstico está visible.
function hayPronosticoVisible() {
  return Object.values(capasPron).some(c => map.hasLayer(c));
}

// Sincroniza la leyenda de pronóstico con el estado real de las capas.
function sincronizarLeyendaPronostico() {
  if (!controlLeyendaPron) return;
  const visible = hayPronosticoVisible();
  const enMapa = map.hasLayer(controlLeyendaPron);
  if (visible && !enMapa) {
    controlLeyendaPron.addTo(map);
  } else if (!visible && enMapa) {
    map.removeControl(controlLeyendaPron);
  }
  // Mantener el orden vertical: primero riesgo (más arriba), pronóstico (debajo)
  if (capaDistritos && map.hasLayer(capaDistritos)) {
    capaDistritos.bringToFront();
  }
}

// Aplica una subcapa según el estado del checkbox.
function aplicarSubcapa(nombre, mostrar) {
  const capa = capasPron[nombre];
  if (!capa) return;
  if (mostrar && !map.hasLayer(capa)) {
    capa.addTo(map);
  } else if (!mostrar && map.hasLayer(capa)) {
    map.removeLayer(capa);
  }
  sincronizarLeyendaPronostico();
}

// Aviso de vigencia en el panel superior.
function actualizarAviso(meta) {
  const emitido = new Date(meta.fecha_emision);
  const vigenteHasta = new Date(emitido.getTime() + 72 * 3600 * 1000);
  const ahora = new Date();
  const horasDesdeEmision = (ahora - emitido) / 3600 / 1000;

  const formatoAR = {
    timeZone: 'America/Argentina/Buenos_Aires',
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit'
  };

  document.getElementById('aviso-emitido').textContent =
    emitido.toLocaleString('es-AR', formatoAR);
  document.getElementById('aviso-vigencia').textContent =
    vigenteHasta.toLocaleString('es-AR', formatoAR);

  const estado = document.getElementById('aviso-estado');
  if (horasDesdeEmision > HORAS_VIGENCIA) {
    estado.innerHTML = '<span style="color:#c0392b;">Última actualización hace ' +
      Math.round(horasDesdeEmision) + ' h. El pronóstico puede estar desactualizado.</span>';
  } else {
    estado.innerHTML = '<span style="color:#1a7f37;">Actualizado. Máximo previsto: ' +
      meta.max_mm.toFixed(1) + ' mm en 72 h.</span>';
  }
}

fetch('datos/pronostico/metadata.json')
  .then(function (r) {
    if (!r.ok) throw new Error('HTTP ' + r.status + ' al cargar metadata.json');
    return r.json();
  })
  .then(function (meta) {
    metaPron = meta;

    // Si no hay fecha de emisión, no hay pronóstico que mostrar.
    if (!meta.fecha_emision) {
      document.getElementById('aviso-vencido').style.display = 'block';
      [chkTotal, chkDia1, chkDia2, chkDia3].forEach(c => { if (c) c.disabled = true; });
      return;
    }

    actualizarAviso(meta);

    const bounds = L.latLngBounds(
      [meta.bounds[0][0], meta.bounds[0][1]],
      [meta.bounds[1][0], meta.bounds[1][1]]
    );

    // Crear las 4 capas (no se agregan al mapa todavía)
    capasPron.total = crearCapaPronostico('total', meta, bounds);
    capasPron.dia1  = crearCapaPronostico('dia1',  meta, bounds);
    capasPron.dia2  = crearCapaPronostico('dia2',  meta, bounds);
    capasPron.dia3  = crearCapaPronostico('dia3',  meta, bounds);

    controlLeyendaPron = construirLeyendaPronostico(meta);

    // Estado inicial: las 4 desactivadas (la de distritos sí arranca activa)
    chkTotal.checked = false;
    chkDia1.checked  = false;
    chkDia2.checked  = false;
    chkDia3.checked  = false;

    // Listeners
    chkTotal.addEventListener('change', e => aplicarSubcapa('total', e.target.checked));
    chkDia1 .addEventListener('change', e => aplicarSubcapa('dia1',  e.target.checked));
    chkDia2 .addEventListener('change', e => aplicarSubcapa('dia2',  e.target.checked));
    chkDia3 .addEventListener('change', e => aplicarSubcapa('dia3',  e.target.checked));
  })
  .catch(function (err) {
    console.error('Pronóstico:', err);
    document.getElementById('aviso-vencido').style.display = 'block';
    [chkTotal, chkDia1, chkDia2, chkDia3].forEach(c => { if (c) c.disabled = true; });
  });
