// ══════════════════════════════════════════════
// ANALYSIS WORKSPACE CONTROLS
// Tab switching plus persisted collapse and resize state.
// This module only changes layout; replay state is never read or modified.
// ══════════════════════════════════════════════

var workspaceStorageKey = 'observa-workspace';
var workspaceState = { collapsed: false, height: 210, activeTab: 'equity' };

function getWorkspaceLimits() {
  var viewport = window.innerHeight;
  return {
    min: window.innerWidth <= 760 ? 150 : 130,
    max: Math.max(window.innerWidth <= 760 ? 240 : 220, Math.round(viewport * 0.62))
  };
}

function clampPanelHeight(height) {
  var limits = getWorkspaceLimits();
  return Math.max(limits.min, Math.min(limits.max, Math.round(height)));
}

function saveWorkspaceState() {
  try { sessionStorage.setItem(workspaceStorageKey, JSON.stringify(workspaceState)); } catch (e) {}
}

function applyWorkspaceState(animate) {
  var panel = document.getElementById('bottom-panel');
  var toggle = document.getElementById('panel-toggle');
  workspaceState.height = clampPanelHeight(workspaceState.height);
  panel.style.setProperty('--panel-height', workspaceState.height + 'px');
  panel.classList.toggle('collapsed', workspaceState.collapsed);
  toggle.setAttribute('aria-expanded', String(!workspaceState.collapsed));
  toggle.setAttribute('aria-label', workspaceState.collapsed ? 'Expand analysis panel' : 'Collapse analysis panel');
  showPanel(workspaceState.activeTab, false);
  if (!animate) panel.style.transition = 'none';
  requestAnimationFrame(function() {
    if (!animate) panel.style.removeProperty('transition');
    resizeCharts();
  });
}

function initializeWorkspaceLayout() {
  try {
    var saved = JSON.parse(sessionStorage.getItem(workspaceStorageKey));
    if (saved && typeof saved === 'object') {
      workspaceState.collapsed = saved.collapsed === true;
      workspaceState.height = Number(saved.height) || workspaceState.height;
      workspaceState.activeTab = ['equity', 'trades', 'metrics'].indexOf(saved.activeTab) !== -1 ? saved.activeTab : workspaceState.activeTab;
    }
  } catch (e) {}

  applyWorkspaceState(false);
  setupPanelResize();

  // The chart library owns fixed-size canvases, so observe layout changes
  // rather than relying on a timeout after a CSS transition.
  if (window.ResizeObserver) {
    var workspaceObserver = new ResizeObserver(function() { resizeCharts(); });
    workspaceObserver.observe(document.getElementById('chart-container'));
    workspaceObserver.observe(document.getElementById('equity-panel'));
  }
  document.getElementById('bottom-panel').addEventListener('transitionend', function(event) {
    if (event.propertyName === 'height') resizeCharts();
  });

  window.addEventListener('resize', function() {
    workspaceState.height = clampPanelHeight(workspaceState.height);
    applyWorkspaceState(false);
  });
}

function showPanel(tab, persist) {
  document.getElementById('equity-panel').style.display  = tab === 'equity'  ? 'block' : 'none';
  document.getElementById('trade-log').style.display     = tab === 'trades'  ? 'block' : 'none';
  document.getElementById('metrics-panel').style.display  = tab === 'metrics' ? 'block' : 'none';

  var tabs = document.querySelectorAll('.panel-tab');
  tabs[0].classList.toggle('active', tab === 'equity');
  tabs[1].classList.toggle('active', tab === 'trades');
  tabs[2].classList.toggle('active', tab === 'metrics');
  workspaceState.activeTab = tab;
  if (persist !== false) saveWorkspaceState();
  requestAnimationFrame(resizeCharts);
}

function togglePanel() {
  workspaceState.collapsed = !workspaceState.collapsed;
  saveWorkspaceState();
  applyWorkspaceState(true);
}

function setupPanelResize() {
  var handle = document.getElementById('panel-resize-handle');
  var panel = document.getElementById('bottom-panel');
  var startY, startHeight;

  function beginResize(clientY) {
    if (workspaceState.collapsed) return;
    startY = clientY;
    startHeight = panel.getBoundingClientRect().height;
    document.body.classList.add('is-resizing');
  }

  function moveResize(clientY) {
    if (startY === undefined) return;
    workspaceState.height = clampPanelHeight(startHeight + (startY - clientY));
    panel.style.setProperty('--panel-height', workspaceState.height + 'px');
    resizeCharts();
  }

  function endResize() {
    if (startY === undefined) return;
    startY = undefined;
    document.body.classList.remove('is-resizing');
    saveWorkspaceState();
  }

  handle.addEventListener('pointerdown', function(event) {
    beginResize(event.clientY);
    if (startY !== undefined) handle.setPointerCapture(event.pointerId);
  });
  handle.addEventListener('pointermove', function(event) { moveResize(event.clientY); });
  handle.addEventListener('pointerup', endResize);
  handle.addEventListener('pointercancel', endResize);
  handle.addEventListener('keydown', function(event) {
    if (workspaceState.collapsed) return;
    if (event.key !== 'ArrowUp' && event.key !== 'ArrowDown') return;
    event.preventDefault();
    workspaceState.height = clampPanelHeight(workspaceState.height + (event.key === 'ArrowUp' ? 24 : -24));
    panel.style.setProperty('--panel-height', workspaceState.height + 'px');
    resizeCharts();
    saveWorkspaceState();
  });
}
