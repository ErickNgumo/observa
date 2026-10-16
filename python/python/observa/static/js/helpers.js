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
  var value = Number(n);
  // Negative zero is a floating-point representation, not a negative amount.
  if (Object.is(value, -0)) value = 0;
  return value.toLocaleString('en-US', {
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
// Escapes text for safe insertion into HTML (also used for attribute values).
// Non-strings are converted first, so a malformed report cannot throw here.
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
  });
}
