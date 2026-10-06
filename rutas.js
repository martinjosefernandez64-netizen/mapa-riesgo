/* ============================================================
   CAPA DE RUTAS
   Se carga en un archivo separado para poder quitarla
   del visor sin tocar app.js.
   ============================================================ */

// Referencias globales (se exponen para que app.js las pueda usar
// si hace falta, pero rutas.js funciona de forma autónoma)
window.capaRutas = null;
window.capaRutasHalo = null;

function construirPopupRuta(feature) {
  const p = feature.properties || {};

  function safe(v) {
    if (v === null || v === undefined) return '—';
    const s = String(v).trim();
    return s.length === 0 ? '—' : s;
  }

  let html = '<div class="popup-ruta">';
  html += '<h3>' + safe(p.TIPO) + ' ' + safe(p.NOMBRE) + '</h3>';
  html += '<div class="popup-datos">';
  html += '<div class="linea"><strong>Jurisdicción:</strong> ' + safe(p.JURISDICCI) + '</div>';
  html += '<div class="linea"><strong>Clase:</strong> ' + safe(p.CLASE) + '</div>';
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

function onEachRuta(feature, layer) {
  layer.bindPopup(construirPopupRuta(feature), {
    maxWidth: 300,
    minWidth: 220
  });
  // Efecto hover: engrosar un poco
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

    // Capa 1: halo blanco (se dibuja primero, queda debajo)
    window.capaRutasHalo = L.geoJSON(data, {
      style: estiloRutaHalo,
      interactive: false      // no captura clics, los pasa a la capa negra
    });

    // Capa 2: línea negra (se dibuja arriba)
    window.capaRutas = L.geoJSON(data, {
      style: estiloRutaLinea,
      onEachFeature: onEachRuta
    });

    // NO se agregan al mapa acá. Esperan al checkbox.

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
