/* ============================================================
   CAPAS DE PRECIPITACIÓN ACUMULADA — CHIRPS v3
   Dos capas exclusivas: anual (12 meses móviles) y mensual.
   Se integran con la lógica de capas exclusivas de app.js.
   ============================================================ */

(function () {
  'use strict';

  // ---- Configuración ----
  const TILES_MENSUAL = 'tiles_chirps/mensual/{z}/{x}/{y}.png';
  const TILES_ANUAL   = 'tiles_chirps/anual/{z}/{x}/{y}.png';
  const OPACITY = 0.7;
  const COLORES = ['#ffffcc', '#a1dab4', '#41b6c4', '#2c7fb8', '#253494'];
  const PNG_TRANSPARENTE = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=';

  // ---- Estado ----
  let layerMensual = null;
  let layerAnual   = null;
  let metadata     = null;
  let mapRef       = null;
  let leyendaEl    = null;

  // ---------------------------------------------------------------
  // Inicialización de capas
  // ---------------------------------------------------------------
  function initCapas() {
    layerMensual = L.tileLayer(TILES_MENSUAL, {
      opacity: OPACITY,
      attribution: 'CHIRPS v3.0 — CHC/UCSB',
      maxNativeZoom: 10, maxZoom: 18,
      errorTileUrl: PNG_TRANSPARENTE
    });
    layerAnual = L.tileLayer(TILES_ANUAL, {
      opacity: OPACITY,
      attribution: 'CHIRPS v3.0 — CHC/UCSB',
      maxNativeZoom: 10, maxZoom: 18,
      errorTileUrl: PNG_TRANSPARENTE
    });
  }

  // ---------------------------------------------------------------
  // Metadata (cuantiles y fechas)
  // ---------------------------------------------------------------
  function cargarMetadata() {
    fetch('datos/chirps_metadata.json')
      .then(function (r) {
        if (!r.ok) throw new Error('metadata no disponible');
        return r.json();
      })
      .then(function (data) {
        metadata = data;
        // Rellenar el aviso CHIRPS si existe en el panel
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
  // Leyenda dinámica (5 cuantiles)
  // ---------------------------------------------------------------
  function construirLeyendaHTML(tipo) {
    if (!metadata || !metadata[tipo]) return null;
    const cuantiles = metadata[tipo].cuantiles; // [q20, q40, q60, q80]
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

  function mostrarLeyenda(tipo) {
    ocultarLeyenda();
    const contenedor = document.querySelector('.contenedor-leyendas');
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
  // API pública usada por app.js
  // ---------------------------------------------------------------
  window.chirps = {
    init: function (map) {
      mapRef = map;
      initCapas();
      cargarMetadata();
    },

    activar: function (nombre) {
      if (!mapRef) return;
      if (nombre === 'chirps-anual' && layerAnual && !mapRef.hasLayer(layerAnual)) {
        layerAnual.addTo(mapRef);
      } else if (nombre === 'chirps-mensual' && layerMensual && !mapRef.hasLayer(layerMensual)) {
        layerMensual.addTo(mapRef);
      }
    },

    desactivar: function (nombre) {
      if (!mapRef) return;
      if (nombre === 'chirps-anual' && layerAnual && mapRef.hasLayer(layerAnual)) {
        mapRef.removeLayer(layerAnual);
      } else if (nombre === 'chirps-mensual' && layerMensual && mapRef.hasLayer(layerMensual)) {
        mapRef.removeLayer(layerMensual);
      }
    },

    mostrarLeyenda: function (tipo) {
      mostrarLeyenda(tipo);
    },

    ocultarLeyenda: function () {
      ocultarLeyenda();
    }
  };
})();
