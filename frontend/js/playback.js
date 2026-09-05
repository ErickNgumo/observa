// ══════════════════════════════════════════════
// PLAYBACK CONTROLS (OBS-0010)
// Play, pause, step, previous, reset, jump-to-end and speed control.
// Navigation is bar-granular and deterministic: every move re-derives the
// view from the canonical event stream up to the selected bar.
// ══════════════════════════════════════════════

function maxReplayBarGlobal() {
  return maxReplayBar();
}

function atEnd() {
  return currentBar >= maxReplayBarGlobal() && finished;
}

function nextReplayBar() {
  if (!replayIndex || finished) return;
  var maxK = maxReplayBarGlobal();
  var next = currentBar + 1;
  if (next > maxK) return; // already at final processed bar
  renderToBar(next);
  if (finished) { stopPlayback(); setPlayButton('done'); }
}

function previousReplayBar() {
  stopPlayback();
  isPlaying = false;
  setPlayButton('idle');
  document.getElementById('btn-play').disabled = false;
  document.getElementById('btn-step').disabled = false;
  renderToBar(currentBar - 1);
}

function jumpToEndReplay() {
  stopPlayback();
  isPlaying = false;
  renderToBar(maxReplayBarGlobal());
  if (finished) setPlayButton('done');
}

function togglePlay() {
  if (finished) { resetReplay(); return; }
  isPlaying = !isPlaying;
  if (isPlaying) {
    if (currentBar < 0) renderToBar(0); // start at first bar
    setPlayButton('playing');
    startPlayback();
  } else {
    stopPlayback();
    setPlayButton('idle');
  }
}

function startPlayback() {
  if (finished) return;
  playTimer = setInterval(function () {
    if (finished || currentBar >= maxReplayBarGlobal()) {
      stopPlayback();
      if (currentBar < 0) renderToBar(0);
      return;
    }
    nextReplayBar();
  }, playSpeed);
}

function stopPlayback() {
  if (playTimer) { clearInterval(playTimer); playTimer = null; }
}

function stepOnce() {
  if (isPlaying) togglePlay();
  if (finished) return;
  if (currentBar < 0) {
    renderToBar(0);
  } else {
    nextReplayBar();
  }
}

function resetReplay() {
  stopPlayback();
  isPlaying = false;
  currentBar = -1;
  finished = false;
  currentView = null;
  candleData = [];
  equityData = [];
  balanceData = [];
  tradeMarkers = [];
  tradeLines.forEach(function (l) { chart.removeSeries(l); });
  tradeLines = [];

  clearDrawdownHighlight();

  candleSeries.setData([]);
  fastEmaSeries.setData([]);
  slowEmaSeries.setData([]);
  equitySeries.setData([]);
  if (balanceSeries) balanceSeries.setData([]);
  markerPlugin.setMarkers([]);

  document.getElementById('btn-play').disabled = false;
  document.getElementById('btn-step').disabled = false;
  setPlayButton('idle');
  document.getElementById('stat-balance').textContent = '—';
  document.getElementById('stat-equity').textContent = '—';
  document.getElementById('stat-open').textContent = '—';
  document.getElementById('stat-trades').textContent = '0';
  updateProgressLabel();
  hideRunFailed();
  renderToBar(-1);
}

function updateSpeed() {
  playSpeed = parseInt(document.getElementById('speed-select').value);
  if (isPlaying) { stopPlayback(); startPlayback(); }
}

function toggleLines() {
  showLines = !showLines;
  document.getElementById('btn-lines').classList.toggle('active', showLines);
}
