// State management
let currentStatus = null;
let autoRefreshTimer = null;

// Initialize when DOM ready
document.addEventListener('DOMContentLoaded', () => {
  initTabs();
  fetchStatus();
  autoRefreshTimer = setInterval(fetchStatus, 3000);

  document.getElementById('btn-refresh').addEventListener('click', () => {
    fetchStatus();
  });
});

// Tab Navigation
function initTabs() {
  const tabs = document.querySelectorAll('.tab-btn');
  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      tabs.forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));

      tab.classList.add('active');
      const targetId = tab.getAttribute('data-tab');
      const panel = document.getElementById(targetId);
      if (panel) panel.classList.add('active');

      if (targetId === 'tab-sandbox') {
        refreshPreview();
      }
    });
  });
}

// Fetch Full System Status
async function fetchStatus() {
  try {
    const res = await fetch('/api/status');
    if (!res.ok) return;
    const data = await res.json();
    currentStatus = data;
    renderStatus(data);
  } catch (err) {
    console.error('Failed to fetch status:', err);
  }
}

// Render Status & Diagnostics to UI
function renderStatus(data) {
  const settings = data.settings || {};
  const diag = data.diagnostics || {};

  // 1. Desktop Mode
  const isSandbox = settings.desktop_mode === 'isolated_pip';
  document.getElementById('mode-interactive').classList.toggle('active', !isSandbox);
  document.getElementById('mode-isolated_pip').classList.toggle('active', isSandbox);

  const statusPill = document.getElementById('status-pill');
  const statusPillText = document.getElementById('status-pill-text');
  const modeBadge = document.getElementById('current-mode-badge');

  if (isSandbox) {
    statusPill.className = 'pill';
    statusPill.style.backgroundColor = 'rgba(168, 199, 250, 0.12)';
    statusPill.style.color = 'var(--accent-color)';
    statusPill.style.borderColor = 'rgba(168, 199, 250, 0.3)';
    statusPillText.textContent = 'Virtual Sandbox (PiP)';
    modeBadge.textContent = 'Isolated PiP';
  } else {
    statusPill.className = 'pill pill-active';
    statusPill.style.backgroundColor = '';
    statusPill.style.color = '';
    statusPill.style.borderColor = '';
    statusPillText.textContent = 'Host Desktop';
    modeBadge.textContent = 'Active Screen';
  }

  // 2. Speed Profile
  const currentSpeed = settings.speed || 'normal';
  document.getElementById('speed-badge').textContent = currentSpeed.toUpperCase();
  document.querySelectorAll('#speed-group .btn-chip').forEach(btn => {
    btn.classList.toggle('active', btn.getAttribute('data-speed') === currentSpeed);
  });

  // 3. Action Delay
  const delaySec = settings.action_delay !== undefined ? settings.action_delay : 0.05;
  const delayMs = Math.round(delaySec * 1000);
  document.getElementById('delay-slider').value = delayMs;
  document.getElementById('delay-val').textContent = `${delayMs}ms`;

  // 4. Safety Toggles
  document.getElementById('contention-toggle').checked = !!settings.contention;
  document.getElementById('failsafe-toggle').checked = !!settings.failsafe;

  // 5. Foreground Window
  const fg = diag.foreground_window || {};
  const fgBox = document.getElementById('fg-window-info');
  if (fg.title) {
    fgBox.innerHTML = `
      <div style="font-weight: 600; color: var(--text-primary); margin-bottom: 2px;">${escapeHtml(fg.title)}</div>
      <div style="font-size: 10px; color: var(--text-tertiary);">PID: ${fg.pid} | HWND: ${fg.hwnd} | Class: ${escapeHtml(fg.class_name || 'N/A')}</div>
    `;
  } else {
    fgBox.innerHTML = `<span style="color: var(--text-tertiary);">No active foreground window detected</span>`;
  }

  // 6. Visible Windows List
  const winList = diag.visible_windows || [];
  document.getElementById('win-count-badge').textContent = `${winList.length} Windows`;
  const winContainer = document.getElementById('window-list-container');

  if (winList.length === 0) {
    winContainer.innerHTML = `<div style="color: var(--text-tertiary); padding: 8px;">No visible windows</div>`;
  } else {
    winContainer.innerHTML = winList.map(w => `
      <div class="window-row">
        <div class="win-title" title="${escapeHtml(w.title)}">
          ${w.is_minimized ? '<span style="color: var(--text-tertiary)">[_] </span>' : ''}
          ${escapeHtml(w.title)}
        </div>
        <div class="win-actions">
          <button class="btn-mini" onclick="windowAction('focus', '${escapeHtml(w.title)}')">Focus</button>
          <button class="btn-mini" onclick="windowAction('snap', '${escapeHtml(w.title)}', 'left')">◧</button>
          <button class="btn-mini" onclick="windowAction('snap', '${escapeHtml(w.title)}', 'right')">◨</button>
          <button class="btn-mini" onclick="windowAction('close', '${escapeHtml(w.title)}')">✕</button>
        </div>
      </div>
    `).join('');
  }

  // 7. Monitors Diagnostics
  const monitors = diag.monitors || [];
  const monContainer = document.getElementById('monitor-diag-container');
  if (monitors.length > 0) {
    monContainer.innerHTML = monitors.map((m, idx) => `
      <div class="status-item">
        <span class="status-label">${m.device || 'Monitor ' + (idx + 1)} ${m.is_primary ? '(Primary)' : ''}</span>
        <span class="status-val mono-text">${m.width}x${m.height} @ ${m.dpi_scaling || 100}% DPI</span>
      </div>
    `).join('');
  }
}

// Mode Switching API
async function switchMode(mode) {
  try {
    const res = await fetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ desktop_mode: mode }),
    });
    const data = await res.json();
    if (data.status === 'ok') {
      fetchStatus();
    }
  } catch (err) {
    console.error('Failed to switch mode:', err);
  }
}

// Speed Setting API
async function setSpeed(speed) {
  try {
    const res = await fetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ speed }),
    });
    const data = await res.json();
    if (data.status === 'ok') {
      fetchStatus();
    }
  } catch (err) {
    console.error('Failed to set speed:', err);
  }
}

// Action Delay Slider
let delayDebounce = null;
function onDelayChange(ms) {
  document.getElementById('delay-val').textContent = `${ms}ms`;
  clearTimeout(delayDebounce);
  delayDebounce = setTimeout(async () => {
    try {
      await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action_delay: parseFloat(ms) / 1000.0 }),
      });
    } catch (err) {
      console.error('Failed to update delay:', err);
    }
  }, 200);
}

// Toggle Safety Features
async function toggleSafety(key, val) {
  try {
    const payload = {};
    payload[key] = val;
    await fetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    fetchStatus();
  } catch (err) {
    console.error(`Failed to toggle ${key}:`, err);
  }
}

// Window Quick Actions
async function windowAction(action, target, position) {
  try {
    const payload = { action, target };
    if (position) payload.position = position;
    await fetch('/api/action', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    setTimeout(fetchStatus, 300);
  } catch (err) {
    console.error(`Failed window action ${action}:`, err);
  }
}

// Footer Quick Snap for Foreground Window
async function quickSnap(pos) {
  if (!currentStatus || !currentStatus.diagnostics || !currentStatus.diagnostics.foreground_window) return;
  const fg = currentStatus.diagnostics.foreground_window;
  if (!fg.title) return;

  if (pos === 'minimize') {
    windowAction('state', fg.title, 'minimize');
  } else {
    windowAction('snap', fg.title, pos);
  }
}

// PiP Sandbox Live Preview
function refreshPreview() {
  const img = document.getElementById('preview-image');
  const placeholder = document.getElementById('preview-placeholder');

  img.onload = () => {
    img.style.display = 'block';
    if (placeholder) placeholder.style.display = 'none';
  };
  img.onerror = () => {
    img.style.display = 'none';
    if (placeholder) placeholder.style.display = 'flex';
  };
  img.src = `/api/preview?mode=auto&t=${Date.now()}`;
}

// Launch App in Sandbox
async function launchInSandbox() {
  const input = document.getElementById('sandbox-launch-input');
  const cmd = input.value.trim();
  if (!cmd) return;

  try {
    await fetch('/api/action', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'sandbox_launch', command: cmd }),
    });
    input.value = '';
    setTimeout(() => {
      fetchStatus();
      refreshPreview();
    }, 500);
  } catch (err) {
    console.error('Failed to launch in sandbox:', err);
  }
}

// Destroy Sandbox
async function destroySandbox() {
  try {
    await fetch('/api/action', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'sandbox_destroy' }),
    });
    fetchStatus();
    refreshPreview();
  } catch (err) {
    console.error('Failed to destroy sandbox:', err);
  }
}

// Helper utility
function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}
