/* ============================================================
   CAPA DE RUTAS
   Se carga en un archivo separado para poder quitarla
   del visor sin tocar app.js.
   ============================================================ */

window.capaRutas = null;
window.capaRutasHalo = null;

// Normaliza el valor de CLASE para mostrarlo prolijo
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

function estiloRutaHalo() {
  return {
    color: '#ffffff',
    weight: 7,
    opacity: 0.9,
    lineCap: 'round',
    lineJoin: 'round',
    fill: false
  };
}

function estiloRutaLinea() {
  return {
    color: '#000000',
    weight: 3,
    opacity: 1.0,
    lineCap: 'round',
    lineJoin: 'round',
    fill: false
  };
}

function rutaValida(feature) {
  // Descartar features sin nombre ni jurisdicción (registros vacíos)
  const p = feature.properties || {};
  const nombre = (p.NOMBRE || '').trim();
  return nombre.length > 0;
}

function onEachRuta(feature, layer) {
  layer.bindPopup(construirPopupRuta(feature), {
    maxWidth: 340,
    minWidth: 240
  });
  layer.on('mouseover', function () {
    this.setStyle({ weight: 4 });
  });
  layer.on('mouseout', function () {
    this.setStyle({ weight: 3 });
  });
}

fetch('datos/rutas/rutas.geojson')
  .then(function (r) { return r.json(); })
  .then(function (data) {

    // Filtrar features inválidas al vuelo
    const featuresValidas = (data.features || []).filter(rutaValida);
    const dataFiltrada = {
      type: 'FeatureCollection',
      features: featuresValidas
    };

    console.log('Rutas cargadas: ' + featuresValidas.length +
                ' (de ' + (data.features || []).length + ' totales)');

    // Capa 1: halo blanco
    window.capaRutasHalo = L.geoJSON(dataFiltrada, {
      style: estiloRutaHalo,
      interactive: false
    });

    // Capa 2: línea negra (interactiva)
    window.capaRutas = L.geoJSON(dataFiltrada, {
      style: estiloRutaLinea,
      onEachFeature: onEachRuta
    });

    // Conectar al checkbox
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
      } else {
        map.removeLayer(window.capaRutasHalo);
        map.removeLayer(window.capaRutas);
      }
    });
  })
  .catch(function (err) {
    console.warn('No se pudo cargar la capa de rutas:', err);
    const chk = document.getElementById('chk-rutas');
    if (chk) chk.disabled = true;
  });
