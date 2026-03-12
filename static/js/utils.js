/**
 * NVR Shield – shared JavaScript utilities
 */

'use strict';

/* ── CSRF ─────────────────────────────────────────────────────────────────── */
function getCsrf() {
  return document.cookie
    .split(';')
    .map(c => c.trim())
    .find(c => c.startsWith('csrftoken='))
    ?.split('=')[1] || '';
}

/* ── HTML escaping ────────────────────────────────────────────────────────── */
function esc(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/* ── Toast notifications ──────────────────────────────────────────────────── */
function showToast(msg, type = 'info', duration = 4000) {
  const container = document.getElementById('toastContainer');
  if (!container) return;

  const icons = { success: '✓', error: '✕', info: 'ℹ', warn: '⚠' };
  const toast  = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.innerHTML = `
    <span style="font-weight:700;font-size:14px">${icons[type] || 'ℹ'}</span>
    <span>${esc(msg)}</span>`;

  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transition = 'opacity 0.3s';
    setTimeout(() => toast.remove(), 320);
  }, duration);
}

/* ── AJAX helpers ─────────────────────────────────────────────────────────── */
async function apiPost(url, body = {}, timeout = 60000) {
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), timeout);

  try {
    const resp = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrf(),
        'X-Requested-With': 'XMLHttpRequest',
      },
      body: JSON.stringify(body),
      signal: controller.signal
    });
    clearTimeout(id);
    return resp.json();
  } catch (e) {
    if (e.name === 'AbortError') {
      throw new Error('Request timed out after ' + (timeout / 1000) + 's');
    }
    throw e;
  }
}

async function apiDelete(url) {
  const resp = await fetch(url, {
    method: 'DELETE',
    headers: {
      'X-CSRFToken': getCsrf(),
      'X-Requested-With': 'XMLHttpRequest',
    },
  });
  return resp.json();
}

/* ── Modal helpers ────────────────────────────────────────────────────────── */
function openModal(id)  { document.getElementById(id)?.classList.add('open'); }
function closeModal(id) { document.getElementById(id)?.classList.remove('open'); }

/* ── Confirm dialog ───────────────────────────────────────────────────────── */
function confirmAction(msg) {
  return window.confirm(msg);
}

/* ── Spinner helpers ──────────────────────────────────────────────────────── */
function setLoading(btnEl, spinnerEl, labelEl, loading, labelText = 'Processing…') {
  if (loading) {
    btnEl.disabled = true;
    if (spinnerEl) spinnerEl.style.display = 'inline-block';
    if (labelEl)   labelEl.textContent = labelText;
  } else {
    btnEl.disabled = false;
    if (spinnerEl) spinnerEl.style.display = 'none';
  }
}
