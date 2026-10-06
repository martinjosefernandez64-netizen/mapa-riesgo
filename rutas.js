/* ============================================================
   CAPA DE RUTAS
   Se carga en un archivo separado para poder quitarla
   del visor sin tocar app.js.
   
   Estilos según CLASE:
   - Pavimentado / Concesionado  → línea continua gruesa
   - Mejorado / En ciudad / En construcción → línea discontinua
   - Calzada natural → línea punteada fina
   ============================================================ */

window.capaRutas = null;
window.capaRutasHalo = null;
window.controlLeyendaRutas = null;

// ---------- Normalización de valores ----------
function normalizarClase(clase) {
  if (!clase) return '—';
  const c = String(clase).trim().toLowerCase();
  if (c === 'en ciudad') return 'En ciudad';
  if (c === 'calzada natural') return 'Calzada natural';
  if (c === 'mejorado') return 'Mejorado';
  if (c === 'pavimentado') return 'Pavimentado';
  if (c === 'concesionado') return 'Concesionado';
  if (c === 'en construccion' || c === 'en construcción') return 'En construcción';
  return String(clase).trim();
}

// ---------- Popup ----------
function construirPopupRuta(feature) {
  const p = feature.properties || {};

  function safe(v) {
    if (v === null || v === undefined) return '—';
    const s = String(v).trim();
    return s.length === 0 ? '—' : s;
  }

  const nombre = safe(p.NOMBRE);
  const jurisdiccion = safe(p.JURISDICCI);
  const clase = normalizarClase(p.CLASE);
  const observaciones = safe(p.OBSERVACIO);

  let html = '<div class="popup-ruta">';
  html += '<h3>Ruta ' + nombre + '</h3>';
  html += '<div class="popup-datos">';
  html += '<div class="linea"><strong>Jurisdicción:</strong> ' + jurisdiccion + '</div>';
  html += '<div class="linea"><strong>Clase:</strong> ' + clase + '</div>';
  if (observaciones !== '—') {
    html += '<div class="linea"><strong>Observaciones:</strong> ' + observaciones + '</div>';
  }
  html += '</div>';
  html += '</div>';
  return html;
}

// ---------- Estilos por CLASE ----------
function tipoVisualDeClase(clase) {
  if (!clase) return 'natural';
  const c = String(clase).trim().toLowerCase();

  if (c === 'pavimentado') return 'pavimentado';
  if (c === 'concesionado') return 'pavimentado';
  if (c === 'mejorado') return 'mejorado';
  if (c === 'en ciudad') return 'mejorado';
  if (c === 'en construccion' || c === 'en construcción') return 'mejorado';
  if (c === 'calzada natural') return 'natural';
  return 'natural';
}

function estiloRutaHalo() {
  return {
    color: '#ffffff',
    weight: 8,
    opacity: 0.9,
    lineCap: 'round',
    lineJoin: 'round',
    fill: false
  };
}

function estiloRutaLinea(feature) {
  const tipo = tipoVisualDeClase(feature.properties.CLASE);

  const comunes = {
    color: '#000000',
    opacity: 1.0,
    lineCap: 'round',
    lineJoin: 'round',
    fill: false
  };

  if (tipo === 'pavimentado') {
    return Object.assign({}, comunes, {
      weight: 3.5,
      dashArray: null
    });
  }
  if (tipo === 'mejorado') {
    return Object.assign({}, comunes, {
      weight: 2.5,
      dashArray: '6, 4'
    });
  }
  // natural
  return Object.assign({}, comunes, {
    weight: 2,
    dashArray: '2, 4'
  });
}

// ---------- Interacción ----------
function onEachRuta(feature, layer) {
  const estiloOriginal = estiloRutaLinea(feature);

  layer.bindPopup(construirPopupRuta(feature), {
    maxWidth: 340,
    minWidth: 240
  });

  layer.on('mouseover', function () {
    this.setStyle({
      weight: (estiloOriginal.weight || 3) + 1.5
    });
  });
  layer.on('mouseout', function () {
    this.setStyle({
      weight: estiloOriginal.weight
    });
  });
}

// ---------- Filtro de features válidas ----------
function rutaValida(feature) {
  const p = feature.properties || {};
  const nombre = (p.NOMBRE || '').trim();
  return nombre.length > 0;
}

// ---------- Leyenda ----------
function construirLeyendaRutas() {
  const leyenda = L.control({ position: 'bottomleft' });
  leyenda.onAdd = function () {
    const div = L.DomUtil.create('div', 'leyenda');
    let html = '<div class="leyenda-titulo">Rutas</div>';

    html += '<div class="leyenda-item">' +
            '<svg width="24" height="14"><line x1="0" y1="7" x2="24" y2="7" ' +
            'stroke="black" stroke-width="3.5"/></svg>' +
            '<span>Pavimentado</span></div>';

    html += '<div class="leyenda-item">' +
            '<svg width="24" height="14"><line x1="0" y1="7" x2="24" y2="7" ' +
            'stroke="black" stroke-width="2.5" stroke-dasharray="6,4"/></svg>' +
            '<span>Mejorado</span></div>';

    html += '<div class="leyenda-item">' +
            '<svg width="24" height="14"><line x1="0" y1="7" x2="24" y2="7" ' +
            'stroke="black" stroke-width="2" stroke-dasharray="2,4"/></svg>' +
            '<span>Calzada natural</span></div>';

    div.innerHTML = html;
    return div;
  };
  return leyenda;
}

// ---------- Carga de la capa ----------
fetch('datos/rutas/rutas.geojson')
  .then(function (r) { return r.json(); })
  .then(function (data) {

    const featuresValidas = (data.features || []).filter(rutaValida);
    const dataFiltrada = {
      type: 'FeatureCollection',
      features: featuresValidas
    };

    console.log('Rutas cargadas: ' + featuresValidas.length +
                ' (de ' + (data.features || []).length + ' totales)');

    // Capa 1: halo blanco (debajo, no interactiva)
    window.capaRutasHalo = L.geoJSON(dataFiltrada, {
      style: estiloRutaHalo,
      interactive: false
    });

    // Capa 2: línea negra con estilo según CLASE (arriba, interactiva)
    window.capaRutas = L.geoJSON(dataFiltrada, {
      style: estiloRutaLinea,
      onEachFeature: onEachRuta
    });

    // Conexión con el checkbox
    const chk = document.getElementById('chk-rutas');
    if (!chk) {
      console.warn('No se encontró el checkbox #chk-rutas');
      return;
    }

    chk.addEventListener('change', function (e) {
      if (e.target.checked) {
        window.capaRutasHalo.addTo(map);
        window.capaRutas.addTo(map);
        window.capaRutas.bringToFront();

        if (!window.controlLeyendaRutas) {
          window.controlLeyendaRutas = construirLeyendaRutas();
        }
        window.controlLeyendaRutas.addTo(map);
      } else {
        map.removeLayer(window.capaRutasHalo);
        map.removeLayer(window.capaRutas);
        if (window.controlLeyendaRutas) {
          map.removeControl(window.controlLeyendaRutas);
        }
      }
    });
  })
  .catch(function (err) {
    console.warn('No se pudo cargar la capa de rutas:', err);
    const chk = document.getElementById('chk-rutas');
    if (chk) chk.disabled = true;
  });
