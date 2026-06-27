// ══════════════════════════════════════════════
// PLAYBACK CONTROLS
// Play, pause, step, reset, and speed control
// for the event replay.
// ══════════════════════════════════════════════

function togglePlay() {
  isPlaying = !isPlaying;
  var btn = document.getElementById('btn-play');
  if (isPlaying) {
    btn.textContent = '⏸ Pause';
    btn.classList.add('active');
    startPlayback();
  } else {
    btn.textContent = '▶ Play';
    btn.classList.remove('active');
    stopPlayback();
  }
}

function startPlayback() {
  if (currentIndex >= allEvents.length) return;
  playTimer = setInterval(function() {
    if (currentIndex >= allEvents.length) {
      stopPlayback();
      document.getElementById('btn-play').textContent = '▶ Play';
      document.getElementById('btn-play').classList.remove('active');
      isPlaying = false;
      return;
    }
    processEvent(allEvents[currentIndex]);
    currentIndex++;
  }, playSpeed);
}

function stopPlayback() {
  if (playTimer) { clearInterval(playTimer); playTimer = null; }
}

function stepOnce() {
  if (isPlaying) togglePlay();
  if (currentIndex < allEvents.length) {
    processEvent(allEvents[currentIndex]);
    currentIndex++;
  }
}

function resetReplay() {
  stopPlayback();
  isPlaying    = false;
  currentIndex = 0;
  tradeCount   = 0;
  openTrade    = null;
  barsDrawn    = 0;
  candleData   = [];
  fastEmaData  = [];
  slowEmaData  = [];
  equityData   = [];
  tradeMarkers = [];

  tradeLines.forEach(function(l) { chart.removeSeries(l); });
  tradeLines = [];

  clearDrawdownHighlight();

  candleSeries.setData([]);
  fastEmaSeries.setData([]);
  slowEmaSeries.setData([]);
  equitySeries.setData([]);
  markerPlugin.setMarkers([]);

  document.getElementById('btn-play').textContent = '▶ Play';
  document.getElementById('btn-play').classList.remove('active');
  document.getElementById('stat-balance').textContent  = '10,000.00';
  document.getElementById('stat-pnl').textContent      = '0.00';
  document.getElementById('stat-trades').textContent   = '0';
  document.getElementById('progress-fill').style.width = '0%';
  document.getElementById('stat-progress').textContent = 'Bar 0 / ' + totalBars;
  document.getElementById('trade-log-body').innerHTML  = '';
}

function updateSpeed() {
  playSpeed = parseInt(document.getElementById('speed-select').value);
  if (isPlaying) { stopPlayback(); startPlayback(); }
}

function toggleLines() {
  showLines = !showLines;
  document.getElementById('btn-lines').classList.toggle('active', showLines);
}