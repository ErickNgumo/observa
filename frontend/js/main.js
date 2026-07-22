// ══════════════════════════════════════════════
// BOOT
// Entry point — initialises the charts, loads
// the event log from the server, then waits for
// the user to press Play.
// ══════════════════════════════════════════════

function boot() {
  restoreTheme();
  initCharts();
  initializeInvestigationMode();
  initializeWorkspaceLayout();
  loadEvents().then(function() {
    console.log('Observa ready. Press Play to start replay.');
  });
}

boot();
