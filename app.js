/* ============================================================
   MAPA DE RIESGO - SANTA FE
   Visor Leaflet con dos capas independientes:
   - Distritos con nivel de riesgo (activo por defecto)
   - Pronóstico de precipitación 72 h (desactivado por defecto)
   ============================================================ */

// ---------- Constantes ----------
const PNG_TRANSPARENTE =
  'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=';

const CENTRO_INICIAL = [-31.5, -60.5];
const ZOOM_INICIAL = 7;
const HORAS_VIGENCIA = 30;

// Definición de las 5 clases de riesgo (igual que el ráster original)
const CLASES_RIESGO = [
  { clase: 1, label: 'Riesgo Muy Bajo',          color: '#d9d9d9' },
  { clase: 2, label: 'Riesgo Bajo / Monitoreo',  color: '#fdf2c6' },
  { clase: 3, label: 'Riesgo Moderado',          color: '#e89925' },
  { clase: 4, label: 'Riesgo Alto',              color: '#c14a1c' },
  { clase: 5, label: 'Riesgo Crítico',           color: '#8b1e1e' }
];

// Etiquetas de riesgo_median (mismos textos, pero cortas)
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

// ---------- Inicialización del mapa ----------
const map = L.map('map').setView(CENTRO_INICIAL, ZOOM_INICIAL);

L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '© OpenStreetMap'
}).addTo(map);

// ---------- Capa de distritos con nivel de riesgo ----------
let capaDistritos = null;
let controlLeyendaRiesgo = null;

function construirLeyendaRiesgo() {
  const leyenda = L.control({ position: 'bottomright' });
  leyenda.onAdd = function () {
    const div = L.DomUtil.create('div', 'leyenda');
    let html = '<div class="leyenda-titulo">Nivel de riesgo</div>';
    // Mostrar de mayor a menor para que el "crítico" quede arriba
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
    { clase: 1, etiqueta: 'Bajo (1+2)',  valor: p.b12_ha },
    { clase: 3, etiqueta: 'Moderado',    valor: p.n3_ha },
    { clase: 4, etiqueta: 'Alto',        valor: p.n4_ha },
    { clase: 5, etiqueta: 'Crítico',     valor: p.n5_ha }
  ];
  filas.forEach(function (f) {
    html += '<div class="sup-item">' +
            '<span><span class="sup-color" style="background:' +
            colorDeClase(f.clase) + ';"></span>' + f.etiqueta + '</span>' +
            '<span class="sup-valor">' + formatearNumero(f.valor, 0) + ' ha</span>' +
            '</div>';
  });
  html += '</div>';
  html += '</div>';

  return html;
}

function onEachDistrito(feature, layer) {
  layer.bindPopup(popupDistrito(feature), {
    maxWidth: 340,
    minWidth: 280
  });
  layer.on('mouseover', function () {
    this.setStyle({ weight: 2, color: '#000000' });
  });
  layer.on('mouseout', function () {
    this.setStyle({ weight: 0.6, color: '#333333' });
  });
}

fetch('datos/riesgo/distritos_mediana.geojson')
  .then(function (r) { return r.json(); })
  .then(function (data) {
    capaDistritos = L.geoJSON(data, {
      style: estiloDistrito,
      onEachFeature: onEachDistrito
    });

    controlLeyendaRiesgo = construirLeyendaRiesgo();

    // Arranca activo
    document.getElementById('chk-distritos').checked = true;
    capaDistritos.addTo(map);
    controlLeyendaRiesgo.addTo(map);

    document.getElementById('chk-distritos')
      .addEventListener('change', function (e) {
        if (e.target.checked) {
          capaDistritos.addTo(map);
          controlLeyendaRiesgo.addTo(map);
        } else {
          map.removeLayer(capaDistritos);
          map.removeControl(controlLeyendaRiesgo);
        }
      });
  })
  .catch(function (err) {
    console.warn('No se pudo cargar la capa de distritos:', err);
    document.getElementById('chk-distritos').disabled = true;
  });

// ---------- Capa de pronóstico ----------
let capaPronostico = null;
let controlLeyendaPronostico = null;

function construirLeyendaPronostico(meta) {
  const leyenda = L.control({ position: 'bottomright' });
  leyenda.onAdd = function () {
    const div = L.DomUtil.create('div', 'leyenda');
    let html = '<div class="leyenda-titulo">Precipitación 72 h (mm)</div>';
    const items = meta.escala.slice().reverse();
    items.forEach(function (item) {
      html += '<div class="leyenda-item">' +
              '<span class="leyenda-color" style="background:' + item.color + ';"></span>' +
              '<span>' + item.label + '</span>' +
              '</div>';
    });
    html += '<div class="leyenda-pie">' +
            'Corrida: ' + meta.corrida_wrf + '<br>' +
            'Máx: ' + meta.max_mm.toFixed(1) + ' mm' +
            '</div>';
    div.innerHTML = html;
    return div;
  };
  return leyenda;
}

fetch('datos/pronostico/metadata.json')
  .then(function (r) { return r.json(); })
  .then(function (meta) {
    if (!meta.fecha_emision) {
      document.getElementById('aviso-vencido').style.display = 'block';
      document.getElementById('chk-pronostico').disabled = true;
      return;
    }

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
      estado.innerHTML =
        '<span style="color:#c0392b;">Última actualización hace ' +
        Math.round(horasDesdeEmision) +
        ' h. El pronóstico puede estar desactualizado.</span>';
    } else {
      estado.innerHTML =
        '<span style="color:#1a7f37;">Actualizado. Máximo previsto: ' +
        meta.max_mm.toFixed(1) + ' mm en 72 h.</span>';
    }

    const bounds = L.latLngBounds(
      [meta.bounds[0][0], meta.bounds[0][1]],
      [meta.bounds[1][0], meta.bounds[1][1]]
    );

    capaPronostico = L.tileLayer(
      'tiles_pronostico/{z}/{x}/{y}.png',
      {
        opacity: 0.75,
        tms: false,
        minZoom: 0,
        maxNativeZoom: meta.zoom_max,
        maxZoom: 18,
        bounds: bounds,
        errorTileUrl: PNG_TRANSPARENTE,
        attribution: 'WRF-SMN · acumulado 72 h'
      }
    );

    controlLeyendaPronostico = construirLeyendaPronostico(meta);

    // Arranca desactivado
    const chkPron = document.getElementById('chk-pronostico');
    chkPron.checked = false;

    chkPron.addEventListener('change', function (e) {
      const aviso = document.getElementById('aviso-pronostico');
      if (e.target.checked) {
        capaPronostico.addTo(map);
        controlLeyendaPronostico.addTo(map);
        aviso.style.display = 'block';
      } else {
        map.removeLayer(capaPronostico);
        map.removeControl(controlLeyendaPronostico);
        aviso.style.display = 'none';
      }
    });
  })
  .catch(function (err) {
    console.warn('Pronóstico no disponible:', err);
    document.getElementById('aviso-vencido').style.display = 'block';
    document.getElementById('chk-pronostico').disabled = true;
  });
