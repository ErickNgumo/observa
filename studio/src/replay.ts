// Presentation only: every value and position identity comes from canonical events.
export const replayDelays: Record<string, number> = {
  "0.5×": 400,
  "1×": 200,
  "2×": 100,
  "5×": 40,
  "10×": 20,
  Max: 1,
};
export function executionMarkers(
  events: any[],
  bars: any[],
  cursor: number,
  selected: string | null,
) {
  return events
    .filter(
      (e) =>
        (e.type === "position_opened" || e.type === "position_closed") &&
        e.bar_index <= cursor &&
        bars[e.bar_index],
    )
    .map((e) => {
      const entry = e.type === "position_opened";
      const buy = entry ? e.side === "Buy" : e.side !== "Buy";
      return {
        time: Math.floor(Date.parse(bars[e.bar_index].time) / 1000),
        position: buy ? "belowBar" : "aboveBar",
        price: entry ? e.entry_price : e.exit_price,
        positionId: e.position_id,
        color:
          e.position_id === selected ? "#9953c4" : buy ? "#2878c8" : "#ce5c4f",
        shape: buy ? "arrowUp" : "arrowDown",
        text: `${buy ? "Buy" : "Sell"} ${entry ? "entry" : "exit"}`,
        selected: e.position_id === selected,
      };
    })
    .sort((a, b) => a.time - b.time);
}
export function tradeRange(position: any, cursor: number) {
  const from = position.opened_bar,
    to = Math.min(position.closed_bar ?? cursor, cursor);
  const padding = Math.max(8, (to - from) * 0.2);
  return { from: from - padding, to: to + padding };
}

export function markerPixels(spacing: number, scale = 1): number {
  return Math.max(10, Math.min(16, spacing * 0.8)) * scale;
}

// Exact recorded samples only: missing/warm-up values stay unavailable.
export function indicatorSamples(state: any, time: number) {
  return Object.values(state.series).map((entry: any) => ({
    id: entry.id,
    label: entry.options.label || entry.id,
    color: entry.options.color,
    pane: entry.options.pane,
    value: entry.points.find((point: any) => point.time === time)?.value,
  }));
}

export function tradeConnections(
  events: any[],
  bars: any[],
  cursor: number,
  selected: string | null,
  mode = "all",
) {
  if (mode === "hidden") return [];
  const entries = new Map<string, any>(),
    paths = [];
  for (const e of events) {
    if (e.bar_index > cursor || !bars[e.bar_index]) continue;
    if (e.type === "position_opened") entries.set(e.position_id, e);
    if (e.type !== "position_closed") continue;
    const entry = entries.get(e.position_id);
    if (!entry || (mode === "selected" && e.position_id !== selected)) continue;
    paths.push({
      positionId: e.position_id,
      start: Math.floor(Date.parse(bars[entry.bar_index].time) / 1000),
      end: Math.floor(Date.parse(bars[e.bar_index].time) / 1000),
      entry: entry.entry_price,
      exit: e.exit_price,
      selected: e.position_id === selected,
      color:
        e.position_id === selected
          ? "#9953c4"
          : entry.side === "Buy"
            ? "#2878c8"
            : "#ce5c4f",
    });
  }
  return paths;
}

export function lineExplanation(label: string, type = "series") {
  if (type === "hline")
    return `${label}: a horizontal reference price recorded by the strategy. Its trading meaning is defined in the strategy source.`;
  if (type !== "series")
    return `${label}: a ${type} annotation recorded by the strategy to explain its observations. It does not execute trades.`;
  if (/\b(sma|simple moving average)\b/i.test(label))
    return `${label}: a simple moving average smooths prices by averaging a recent window. The strategy defines the inputs and period; this line displays its recorded values.`;
  if (/\b(ema|exponential moving average)\b/i.test(label))
    return `${label}: an exponential moving average gives more weight to recent prices. The strategy defines its inputs and period; this line displays its recorded values.`;
  if (/\brsi\b/i.test(label))
    return `${label}: RSI is a momentum indicator comparing recent gains and losses. Its period and signal thresholds are defined by the strategy.`;
  return `${label}: an indicator series recorded by the strategy. Its exact calculation is defined in the strategy source; gaps mean no value was recorded.`;
}
