/**
 * NVR Shield – Dashboard JavaScript
 *
 * Responsibilities:
 *   - Camera grid: build, resize, clear
 *   - Drag & drop: sidebar camera → grid cell
 *   - Double-click: auto-add to first empty slot
 *   - Multi-select: select + "Add to Grid" batch action
 *   - Add NVR modal: connect → save flow
 *   - Delete NVR / camera with live DOM update
 *   - Stat bar update
 *   - Topbar clock
 */

'use strict';

/* ── State ────────────────────────────────────────────────────────────────── */
let gridCols    = 2;
let gridRows    = 2;
let dragPayload = null;       // {name, previewUrl, rawPreviewUrl, streamUrl} being dragged
let selectedIds = new Set();  // selected camera IDs (strings)
let pendingNvr  = null;       // data from connect step, pending save

const gridEl = () => document.getElementById('camGrid');

/* ── Boot ─────────────────────────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
  buildGrid(2, 2);
  startClock();
  updateStats();

  // Close modal on backdrop click
  document.getElementById('addNvrModal')?.addEventListener('click', e => {
    if (e.target === document.getElementById('addNvrModal')) closeAddNvrModal();
  });

  // Keyboard: Esc closes modal
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') closeAddNvrModal();
  });
});

/* ── Clock ────────────────────────────────────────────────────────────────── */
function startClock() {
  const el = document.getElementById('topClock');
  const tick = () => {
    if (el) el.textContent = new Date().toLocaleTimeString('en-US', { hour12: false });
  };
  tick();
  setInterval(tick, 1000);
}

/* ── Stats ────────────────────────────────────────────────────────────────── */
function updateStats() {
  const nvrCount = document.querySelectorAll('.nvr-item').length;
  const camCount = document.querySelectorAll('.cam-row').length;
  const active   = document.querySelectorAll('.grid-cell.occupied').length;
  const setEl = (id, val) => { const e = document.getElementById(id); if (e) e.textContent = val; };
  setEl('statNvr',    nvrCount + ' NVR' + (nvrCount !== 1 ? 's' : ''));
  setEl('statCam',    camCount + ' Camera' + (camCount !== 1 ? 's' : ''));
  setEl('statActive', active   + ' Active');
}

/* ── Grid management ──────────────────────────────────────────────────────── */
function buildGrid(cols, rows) {
  gridCols = cols;
  gridRows = rows;
  const grid  = gridEl();
  const total = cols * rows;

  grid.style.gridTemplateColumns = `repeat(${cols}, 1fr)`;
  grid.style.gridTemplateRows    = `repeat(${rows}, 1fr)`;
  grid.innerHTML = '';

  for (let i = 0; i < total; i++) {
    grid.appendChild(makeEmptyCell(i));
  }
  updateStats();
}

function makeEmptyCell(index) {
  const cell = document.createElement('div');
  cell.className = 'grid-cell';
  cell.dataset.index = index;
  cell.innerHTML = `
    <div class="cell-idx">${String(index + 1).padStart(2, '0')}</div>
    <div class="cell-placeholder">
      <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1">
        <rect x="2" y="7" width="20" height="15" rx="2"/>
        <polyline points="17,2 12,7 7,2"/>
      </svg>
      <div class="cell-placeholder-txt">Drop camera here</div>
    </div>`;

  cell.addEventListener('dragover',   e => { e.preventDefault(); cell.classList.add('drag-over'); });
  cell.addEventListener('dragleave',  ()  => cell.classList.remove('drag-over'));
  cell.addEventListener('drop',       e  => { e.preventDefault(); handleCellDrop(cell); });
  return cell;
}

function setGrid(cols, rows, btn) {
  document.querySelectorAll('.layout-btn').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  buildGrid(cols, rows);
}

function applyCustomGrid() {
  const c = Math.min(Math.max(parseInt(document.getElementById('customCols').value) || 3, 1), 12);
  const r = Math.min(Math.max(parseInt(document.getElementById('customRows').value) || 3, 1), 12);
  setGrid(c, r, null);
}

function clearGrid() {
  buildGrid(gridCols, gridRows);
}

/* ── Load/unload stream ───────────────────────────────────────────────────── */
function loadStream(cell, name, previewUrl, rawPreviewUrl, streamUrl) {
  const idx = cell.dataset.index;
  cell.className = 'grid-cell occupied';
  cell.dataset.index = idx;
  cell.innerHTML = `
    <div class="cell-idx">${String(parseInt(idx) + 1).padStart(2, '0')}</div>
    <div class="cell-bar">
      <span class="dot dot-green"></span>
      <span class="cell-bar-name">${esc(name)}</span>
      <button class="cell-close-btn" title="Remove stream">
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
          <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
        </svg>
      </button>
    </div>
    <div class="stream-container">
      <img class="cell-stream-img" 
           src="${esc(streamUrl)}" 
           alt="${esc(name)}"
           onerror="this.closest('.grid-cell').classList.add('load-failed');">
    </div>
    <div class="iframe-fail-notice">
      <p style="color: var(--accent2); font-weight: bold; margin-bottom: 5px;">Stream Load Issue</p>
      <p style="font-size: 11px; color: var(--muted); margin-bottom: 10px;">RTSP stream could not be opened or decoded.</p>
      <div class="fail-actions" style="display: flex; flex-direction: column; gap: 8px;">
        <button class="btn btn-xs btn-outline" onclick="const cell=this.closest('.grid-cell'); cell.classList.remove('load-failed'); const img=cell.querySelector('.cell-stream-img'); const src=img.src.split('?')[0]; img.src=src + '?t=' + Date.now();">Retry Stream</button>
        <a href="${esc(rawPreviewUrl || previewUrl)}" target="_blank" class="btn btn-xs btn-primary">Open NVR Web Page (Auth Fix)</a>
        <p style="font-size: 10px; color: var(--muted); margin-top: 5px;">Tip: Some NVRs require you to login once in a new tab to authorize the browser.</p>
      </div>
    </div>`;

  // Check for loading failure after 10s
  setTimeout(() => {
    const img = cell.querySelector('.cell-stream-img');
    if (img && !img.complete) {
      // Still not loaded after 10s might be a hang, but img.onerror is more reliable
    }
  }, 10000);

  // Re-attach drop events
  cell.addEventListener('dragover',  e => { e.preventDefault(); cell.classList.add('drag-over'); });
  cell.addEventListener('dragleave', ()  => cell.classList.remove('drag-over'));
  cell.addEventListener('drop',      e  => { e.preventDefault(); handleCellDrop(cell); });

  // Close button
  cell.querySelector('.cell-close-btn')?.addEventListener('click', () => {
    const newCell = makeEmptyCell(parseInt(idx));
    cell.replaceWith(newCell);
    updateStats();
  });

  updateStats();
}

/* ── Drag & drop ──────────────────────────────────────────────────────────── */
function onCamDragStart(el) {
  dragPayload = {
    name:           el.dataset.camName,
    previewUrl:     el.dataset.previewUrl,
    rawPreviewUrl:  el.dataset.rawPreviewUrl,
    streamUrl:      el.dataset.streamUrl,
  };
}

function handleCellDrop(cell) {
  cell.classList.remove('drag-over');
  if (!dragPayload) return;
  loadStream(cell, dragPayload.name, dragPayload.previewUrl, dragPayload.rawPreviewUrl, dragPayload.streamUrl);
  dragPayload = null;
}

/* ── Double-click: auto-add ───────────────────────────────────────────────── */
function camDblClick(el) {
  const empty = document.querySelector('.grid-cell:not(.occupied)');
  if (!empty) {
    showToast('No empty grid slots – expand the layout.', 'warn');
    return;
  }
  loadStream(empty, el.dataset.camName, el.dataset.previewUrl, el.dataset.rawPreviewUrl, el.dataset.streamUrl);
  showToast(`"${el.dataset.camName}" added to grid`, 'success');
}

/* ── Multi-select ─────────────────────────────────────────────────────────── */
function toggleCamSelect(el) {
  const id = el.dataset.camId;
  if (selectedIds.has(id)) {
    selectedIds.delete(id);
    el.classList.remove('selected');
  } else {
    selectedIds.add(id);
    el.classList.add('selected');
  }
  refreshSelectUI();
}

function refreshSelectUI() {
  const n        = selectedIds.size;
  const countEl  = document.getElementById('selCount');
  const addBtn   = document.getElementById('btnAddSelected');
  if (n > 0) {
    if (countEl) { countEl.textContent = `${n} selected`; countEl.style.display = 'block'; }
    if (addBtn)  addBtn.style.display = 'block';
  } else {
    if (countEl) countEl.style.display = 'none';
    if (addBtn)  addBtn.style.display  = 'none';
  }
}

function addSelectedToGrid() {
  const rows = document.querySelectorAll('.cam-row.selected');
  let added = 0;
  rows.forEach(row => {
    const empty = document.querySelector('.grid-cell:not(.occupied)');
    if (empty) {
      loadStream(empty, row.dataset.camName, row.dataset.previewUrl, row.dataset.rawPreviewUrl, row.dataset.streamUrl);
      added++;
    }
  });
  if (added) showToast(`${added} camera(s) added`, 'success');
  else       showToast('No empty slots available', 'warn');

  // Clear selection
  selectedIds.clear();
  document.querySelectorAll('.cam-row.selected').forEach(r => r.classList.remove('selected'));
  refreshSelectUI();
}

/* ── Sidebar expand/collapse ──────────────────────────────────────────────── */
function toggleNvrItem(rowEl) {
  rowEl.closest('.nvr-item')?.classList.toggle('open');
}

/* ── Sync NVR ────────────────────────────────────────────────────────────── */
async function syncNvr(nvrId, name, btnEl) {
  if (!confirmAction(`Sync cameras for "${name}"? This will refresh all channels.`)) return;

  btnEl.disabled = true;
  btnEl.style.opacity = '0.5';
  
  try {
    const resp = await fetch(`/nvr/sync/${nvrId}/`, {
      method: 'POST',
      headers: { 'X-CSRFToken': CSRF_TOKEN }
    });
    const data = await resp.json();

    if (data.success) {
      showToast(`Sync complete! Found ${data.camera_count} cameras.`, 'success');
      // Reload the page to refresh the sidebar tree
      setTimeout(() => window.location.reload(), 1000);
    } else {
      showToast(`Sync failed: ${data.error}`, 'error');
    }
  } catch (e) {
    showToast(`Network error: ${e}`, 'error');
  } finally {
    btnEl.disabled = false;
    btnEl.style.opacity = '1';
  }
}

/* ── Delete NVR ───────────────────────────────────────────────────────────── */
async function deleteNvr(nvrId, name, rowEl) {
  if (!confirmAction(`Delete NVR "${name}" and all its cameras?`)) return;
  try {
    const data = await apiDelete(`/nvr/delete/${nvrId}/`);
    if (data.success) {
      rowEl.closest('.nvr-item')?.remove();
      showToast(`NVR "${name}" deleted`, 'success');
      updateStats();
    } else {
      showToast(data.error || 'Delete failed', 'error');
    }
  } catch (e) {
    showToast('Network error', 'error');
  }
}

/* ── Delete Camera ────────────────────────────────────────────────────────── */
async function deleteCam(camId, name, btnEl) {
  if (!confirmAction(`Delete camera "${name}"?`)) return;
  try {
    const data = await apiDelete(`/camera/delete/${camId}/`);
    if (data.success) {
      btnEl.closest('.cam-row')?.remove();
      showToast(`Camera "${name}" deleted`, 'success');
      updateStats();
    } else {
      showToast(data.error || 'Delete failed', 'error');
    }
  } catch (e) {
    showToast('Network error', 'error');
  }
}

/* ── Add NVR Modal ────────────────────────────────────────────────────────── */
function openAddNvrModal() {
  resetAddNvrForm();
  openModal('addNvrModal');
}

function closeAddNvrModal() {
  closeModal('addNvrModal');
}

function resetAddNvrForm() {
  ['nvrLocation','nvrUrl','nvrPort','nvrPassword'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = '';
  });
  const user = document.getElementById('nvrUsername');
  if (user) user.value = 'admin';

  document.getElementById('connectPanel')?.classList.remove('visible');
  document.getElementById('modalAlert')?.setAttribute('class', 'alert');
  document.getElementById('modalAlert')?.style.setProperty('display','none');
  document.getElementById('btnSaveNvr')?.style.setProperty('display','none');
  pendingNvr = null;
}

/* Password visibility toggle in modal */
function toggleModalPwd() {
  const inp = document.getElementById('nvrPassword');
  const ico = document.getElementById('modalEyeIco');
  if (!inp) return;
  const show = inp.type === 'password';
  inp.type = show ? 'text' : 'password';
  if (ico) ico.innerHTML = show
    ? `<path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/>`
    : `<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>`;
}

/* Connect step */
async function connectNvr() {
  const url      = document.getElementById('nvrUrl')?.value.trim();
  const port     = document.getElementById('nvrPort')?.value.trim();
  const username = document.getElementById('nvrUsername')?.value.trim();
  const password = document.getElementById('nvrPassword')?.value || '';

  if (!url) { showModalAlert('NVR URL is required.', 'error'); return; }
  if (!username) { showModalAlert('Username is required.', 'error'); return; }

  hideModalAlert();
  setConnectLoading(true, 'Connecting to NVR...');

  try {
    // Stage 1: Basic connection
    setConnectLoading(true, 'Detecting brand and protocol...');
    const data = await apiPost('/nvr/connect/', { url, port, username, password });

    if (!data.success) {
      showModalAlert(data.error || 'Connection failed.', 'error');
      return;
    }

    // Stage 2: Success
    pendingNvr = { url: data.base_url || url, port, username, password, brand: data.brand, cameras: data.cameras };
    renderConnectPanel(data);
    document.getElementById('btnSaveNvr')?.style.setProperty('display','inline-flex');
    showModalAlert(`Connected! Detected ${data.camera_count} camera(s).`, 'success');

  } catch (e) {
    showModalAlert('Network error: ' + e.message, 'error');
  } finally {
    setConnectLoading(false);
  }
}

function renderConnectPanel(data) {
  const brandHtml = `
    <span class="badge badge-${esc(data.brand)}">${esc(data.brand)}</span>
    <span style="font-size:13px;color:var(--muted)">${data.camera_count} camera(s) detected</span>`;

  const camsHtml = data.cameras.map((c, i) => `
    <div class="cam-preview-row">
      <span class="dot dot-green"></span>
      <span style="flex:1">${esc(c.name)}</span>
      <span style="font-family:var(--font-mono);font-size:10px;color:var(--muted)">CH${c.channel || i+1}</span>
    </div>`).join('');

  document.getElementById('detectedBrand').innerHTML = brandHtml;
  document.getElementById('camPreviewList').innerHTML = camsHtml || '<div style="color:var(--muted);font-size:12px">No cameras detected</div>';
  document.getElementById('connectPanel')?.classList.add('visible');
}

/* Save step */
async function saveNvr() {
  if (!pendingNvr) return;

  const location = document.getElementById('nvrLocation')?.value.trim();
  if (!location) { showModalAlert('Please enter a location/label.', 'error'); return; }

  pendingNvr.location = location;

  try {
    const data = await apiPost('/nvr/save/', pendingNvr);
    if (!data.success) {
      showModalAlert(data.error || 'Save failed.', 'error');
      return;
    }

    addNvrToSidebar(data);
    closeAddNvrModal();
    showToast(`NVR "${location}" added with ${data.cameras.length} camera(s)`, 'success');
    updateStats();

    // Remove "empty sidebar" notice if present
    document.getElementById('sidebarEmpty')?.remove();

  } catch (e) {
    showModalAlert('Network error: ' + e.message, 'error');
  }
}

/* Build and inject NVR item into sidebar */
function addNvrToSidebar(data) {
  const camsHtml = data.cameras.length
    ? data.cameras.map(c => makeCamRowHtml(c, data.nvr_id)).join('')
    : '<div class="cam-empty">No cameras</div>';

  const div = document.createElement('div');
  div.className  = 'nvr-item open';
  div.dataset.nvrId = data.nvr_id;
  div.innerHTML = `
    <div class="nvr-row" onclick="toggleNvrItem(this)">
      <span class="nvr-arrow">
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
          <polyline points="9,18 15,12 9,6"/>
        </svg>
      </span>
      <span class="badge badge-${esc(data.brand)}">${esc(data.brand)}</span>
      <span class="nvr-name ellipsis" title="${esc(data.nvr_location)}">${esc(data.nvr_location)}</span>
      <div class="nvr-actions">
        <button class="nvr-act-btn" title="Delete NVR"
          onclick="event.stopPropagation();deleteNvr(${data.nvr_id},'${esc(data.nvr_location)}',this)">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="3,6 5,6 21,6"/>
            <path d="M19,6v14a2,2,0,0,1-2,2H7a2,2,0,0,1-2-2V6"/>
            <path d="M8,6V4a2,2,0,0,1,2-2h4a2,2,0,0,1,2,2v2"/>
          </svg>
        </button>
      </div>
    </div>
    <div class="cam-list">${camsHtml}</div>`;

  document.getElementById('nvrTree')?.appendChild(div);
}

function makeCamRowHtml(cam, nvrId) {
  return `
    <div class="cam-row"
         data-cam-id="${cam.id}"
         data-cam-name="${esc(cam.name)}"
         data-preview-url="${esc(cam.preview_url)}"
         data-raw-preview-url="${esc(cam.raw_preview_url || cam.preview_url)}"
         data-nvr-id="${nvrId}"
         draggable="true"
         ondragstart="onCamDragStart(this)"
         ondblclick="camDblClick(this)"
         onclick="toggleCamSelect(this)">
      <span class="dot dot-green"></span>
      <span class="cam-name-text ellipsis">${esc(cam.name)}</span>
      ${cam.channel ? `<span class="cam-ch">CH${cam.channel}</span>` : ''}
      <button class="cam-del-btn" title="Delete camera"
        onclick="event.stopPropagation();deleteCam(${cam.id},'${esc(cam.name)}',this)">
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
          <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
        </svg>
      </button>
    </div>`;
}

/* ── Modal alert helpers ──────────────────────────────────────────────────── */
function showModalAlert(msg, type = 'info') {
  const el = document.getElementById('modalAlert');
  if (!el) return;
  el.className = `alert alert-${type}`;
  el.innerHTML = `
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <circle cx="12" cy="12" r="10"/>
      <line x1="12" y1="8" x2="12" y2="12"/>
      <line x1="12" y1="16" x2="12.01" y2="16"/>
    </svg>
    <span>${esc(msg)}</span>`;
  el.style.display = 'flex';
}

function hideModalAlert() {
  const el = document.getElementById('modalAlert');
  if (el) el.style.display = 'none';
}

/* ── Connect button loading ───────────────────────────────────────────────── */
function setConnectLoading(loading, labelText = 'Connecting…') {
  const btn     = document.getElementById('btnConnect');
  const spinner = document.getElementById('connectSpinner');
  const label   = document.getElementById('connectLabel');
  if (!btn) return;
  btn.disabled = loading;
  if (spinner) spinner.style.display = loading ? 'inline-block' : 'none';
  if (label)   label.textContent = loading ? labelText : 'Connect';
}
