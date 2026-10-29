/* ============================================================
   CAPA DE RUTAS — Superponible con cualquier capa exclusiva
   ============================================================ */

window.capaRutas = null;
window.capaRutasHalo = null;
window.controlLeyendaRutas = null;

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
  if (observaciones !== '—') html += '<div class="linea"><strong>Observaciones:</strong> ' + observaciones + '</div>';
  html += '</div></div>';
  return html;
}

function tipoVisualDeClase(clase) {
  if (!clase) return 'natural';
  const c = String(clase).trim().toLowerCase();
  if (c === 'pavimentado' || c === 'concesionado') return 'pavimentado';
  if (c === 'mejorado' || c === 'en ciudad' || c === 'en construccion' || c === 'en construcción') return 'mejorado';
  return 'natural';
}

function estiloRutaHalo() {
  return { color: '#ffffff', weight: 8, opacity: 0.9, lineCap: 'round', lineJoin: 'round', fill: false };
}

function estiloRutaLinea(feature) {
  const tipo = tipoVisualDeClase(feature.properties.CLASE);
  const comunes = { color: '#000000', opacity: 1.0, lineCap: 'round', lineJoin: 'round', fill: false };
  if (tipo === 'pavimentado') return Object.assign({}, comunes, { weight: 3.5, dashArray: null });
  if (tipo === 'mejorado')    return Object.assign({}, comunes, { weight: 2.5, dashArray: '6, 4' });
  return Object.assign({}, comunes, { weight: 2, dashArray: '2, 4' });
}

function onEachRuta(feature, layer) {
  const estiloOriginal = estiloRutaLinea(feature);
  layer.bindPopup(construirPopupRuta(feature), { maxWidth: 340, minWidth: 240 });
  layer.on('mouseover', function () { this.setStyle({ weight: (estiloOriginal.weight || 3) + 1.5 }); });
  layer.on('mouseout',  function () { this.setStyle({ weight: estiloOriginal.weight }); });
}

function rutaValida(feature) {
  const p = feature.properties || {};
  return ((p.NOMBRE || '').trim()).length > 0;
}

function construirLeyendaRutas() {
  const leyenda = L.control({ position: 'bottomleft' });
  leyenda.onAdd = function () {
    const div = L.DomUtil.create('div', 'leyenda-caja');
    let html = '<div class="leyenda-titulo">Rutas</div>';
    html += '<div class="leyenda-item"><svg width="24" height="14"><line x1="0" y1="7" x2="24" y2="7" stroke="black" stroke-width="3.5"/></svg><span>Pavimentado</span></div>';
    html += '<div class="leyenda-item"><svg width="24" height="14"><line x1="0" y1="7" x2="24" y2="7" stroke="black" stroke-width="2.5" stroke-dasharray="6,4"/></svg><span>Mejorado</span></div
