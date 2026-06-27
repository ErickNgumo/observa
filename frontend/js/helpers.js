// ══════════════════════════════════════════════
// SMALL SHARED HELPERS
// Pure utility functions used across multiple
// files. No state, no side effects beyond
// formatting and lookups.
// ══════════════════════════════════════════════

// Converts an ISO timestamp string into Unix seconds.
// TradingView expects time as Unix seconds, not ms.
function toUnix(iso) {
  return Math.floor(new Date(iso).getTime() / 1000);
}

// Formats a number with a fixed number of decimals
// and thousands separators, e.g. 10000 -> "10,000.00"
function fmtNum(n, dec) {
  return Number(n).toLocaleString('en-US', {
    minimumFractionDigits: dec,
    maximumFractionDigits: dec
  });
}

// Finds the index of the first BarReceived event
// at or after the given Unix time. Used by the
// drawdown "click to replay" feature to know
// where to jump to in allEvents.
function findEventIndexNearTime(unixTime) {
  for (var i = 0; i < allEvents.length; i++) {
    if (allEvents[i].event_type === 'BarReceived') {
      if (toUnix(allEvents[i].timestamp) >= unixTime) {
        return i;
      }
    }
  }
  return 0;
}