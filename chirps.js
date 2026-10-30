/* ============================================================
   CAPAS DE PRECIPITACIÓN ACUMULADA — CHIRPS v3
   ============================================================ */

(function () {
  'use strict';

  const TILES_MENSUAL = 'tiles_chirps/mensual/{z}/{x}/{y}.png';
  const TILES_ANUAL   = 'tiles_chirps/anual/{z}/{x}/{y}.png';
  const OPACITY = 0.85; 
  const COLORES = ['#ffffcc', '#a1dab4', '#41b6c4', '#2c7fb8', '#253494'];
  const PNG_TRANSPARENTE = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=';

  const MAX_NATIVE_ZOOM = 8;
  const BOUNDS_SANTA_FE = [[-34.0, -63.5], [-27.5, -58.0]];

  let layerMensual = null;
  let layerAnual   = null;
  let metadata     = null;
  let mapRef       = null;
  let leyendaEl    = null;
  let tipoPendiente = null;

  // ---------------------------------------------------------------
  // Asegurar que las capas existan antes de usarlas
  // ---------------------------------------------------------------
  function asegurarCapas() {
    if (!layerMensual) {
      layerMensual = L.tileLayer(TILES_MENSUAL, {
        opacity: OPACITY,
        attribution: 'CHIRPS v3.0 — CHC/UCSB',
        maxNativeZoom: MAX_NATIVE_ZOOM,
        maxZoom: 18,
        bounds: BOUNDS_SANTA_FE,
        errorTileUrl: PNG_TRANSPARENTE
      });
    }
    if (!layerAnual) {
      layerAnual = L.tileLayer(TILES_ANUAL, {
        opacity: OPACITY,
        attribution: 'CHIRPS v3.0 — CHC/UCSB',
        maxNativeZoom: MAX_NATIVE_ZOOM,
        maxZoom: 18,
        bounds: BOUNDS_SANTA_FE,
        errorTileUrl: PNG_TRANSPARENTE
      });
    }
  }

  // ---------------------------------------------------------------
  // Metadata
  // ---------------------------------------------------------------
  function cargarMetadata() {
    fetch('datos/chirps_metadata.json')
      .then(function (r) {
        if (!r.ok) throw new Error('metadata no disponible');
        return r.json();
      })
      .then(function (data) {
        metadata = data;
        if (tipoPendiente) {
          mostrarLeyenda(tipoPendiente);
          tipoPendiente = null;
        }
        const aviso = document.getElementById('aviso-chirps');
        if (aviso) {
          const elM = document.getElementById('chirps-mensual-fecha');
          const elA = document.getElementById('chirps-anual-rango');
          if (elM && metadata.mensual && metadata.mensual.rango) {
            elM.textContent = metadata.mensual.rango;
          }
          if (elA && metadata.anual && metadata.anual.fecha_fin) {
            elA.textContent = 'hasta ' + metadata.anual.fecha_fin;
          }
          aviso.style.display = 'block';
        }
      })
      .catch(function (err) {
        console.warn('CHIRPS: no se pudo cargar metadata.json', err);
      });
  }

  // ---------------------------------------------------------------
  // Leyenda dinámica
  // ---------------------------------------------------------------
  function construirLeyendaHTML(tipo) {
    if (!metadata || !metadata[tipo]) return null;
    const cuantiles = metadata[tipo].cuantiles;
    const etiquetas = [
      '0 – ' + Math.round(cuantiles[0]) + ' mm',
      Math.round(cuantiles[0]) + ' – ' + Math.round(cuantiles[1]) + ' mm',
      Math.round(cuantiles[1]) + ' – ' + Math.round(cuantiles[2]) + ' mm',
      Math.round(cuantiles[2]) + ' – ' + Math.round(cuantiles[3]) + ' mm',
      '> ' + Math.round(cuantiles[3]) + ' mm'
    ];

    const div = L.DomUtil.create('div', 'leyenda-caja');
    const titulo = tipo === 'anual'
      ? 'Precipitación 12 meses (mm)'
      : 'Precipitación último mes (mm)';
    let html = '<div class="leyenda-titulo">' + titulo + '</div>';
    for (let i = 0; i < 5; i++) {
      html += '<div class="leyenda-item">' +
              '<span class="leyenda-color" style="background:' + COLORES[i] + ';"></span>' +
              '<span>' + etiquetas[i] + '</span></div>';
    }
    const pie = tipo === 'anual'
      ? 'Acumulado 12 meses móviles · CHIRPS v3.0'
      : 'Último mes completo · CHIRPS v3.0';
    html += '<div class="leyenda-pie">' + pie + '</div>';
    div.innerHTML = html;
    return div;
  }

  function getContenedorLeyendas() {
    let cont = document.querySelector('.contenedor-leyendas');
    if (!cont && mapRef) {
      const control = L.control({ position: 'topleft' });
      control.onAdd = function () {
        return L.DomUtil.create('div', 'contenedor-leyendas');
      };
      control.addTo(mapRef);
      cont = document.querySelector('.contenedor-leyendas');
    }
    return cont;
  }

  function mostrarLeyenda(tipo) {
    if (!metadata) {
      tipoPendiente = tipo;
      return;
    }
    ocultarLeyenda();
    const contenedor = getContenedorLeyendas();
    if (!contenedor) return;
    
    const el = construirLeyendaHTML(tipo);
    if (!el) return;
    leyendaEl = el;
    contenedor.appendChild(leyendaEl);
  }

  function ocultarLeyenda() {
    const contenedor = document.querySelector('.contenedor-leyendas');
    if (leyendaEl && contenedor && contenedor.contains(leyendaEl)) {
      contenedor.removeChild(leyendaEl);
    }
    leyendaEl = null;
  }

  // ---------------------------------------------------------------
  // API pública
  // ---------------------------------------------------------------
  window.chirps = {
    init: function (map) {
      mapRef = map;
      asegurarCapas();
      cargarMetadata();
    },

    activar: function (nombre) {
      if (!mapRef) return;
      asegurarCapas();
      if (nombre === 'chirps-anual' && !mapRef.hasLayer(layerAnual)) {
        layerAnual.addTo(mapRef);
      } else if (nombre === 'chirps-mensual' && !mapRef.hasLayer(layerMensual)) {
        layerMensual.addTo(mapRef);
      }
    },

    desactivar: function (nombre) {
      if (!mapRef) return;
      if (nombre === 'chirps-anual' && mapRef.hasLayer(layerAnual)) {
        mapRef.removeLayer(layerAnual);
      } else if (nombre === 'chirps-mensual' && mapRef.hasLayer(layerMensual)) {
        mapRef.removeLayer(layerMensual);
      }
    },

    mostrarLeyenda: function (tipo) { mostrarLeyenda(tipo); },
    ocultarLeyenda: function () { ocultarLeyenda(); }
  };
})();

// Auto-inicialización: si el mapa ya existe, inicializar CHIRPS automáticamente
if (window.map && window.chirps && !window.chirps._iniciado) {
  window.chirps.init(window.map);
  window.chirps._iniciado = true;
}
