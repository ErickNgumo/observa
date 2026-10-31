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
      const entry = e.type === "position_opened",
        buy = e.side === "Buy";
      return {
        time: Math.floor(Date.parse(bars[e.bar_index].time) / 1000),
        position: entry === buy ? "belowBar" : "aboveBar",
        color:
          e.position_id === selected
            ? "#9953c4"
            : (entry ? buy : e.net_realized_pnl >= 0)
              ? "#178363"
              : "#c35449",
        shape: entry ? (buy ? "arrowUp" : "arrowDown") : "circle",
        text: `${entry ? (buy ? "Buy" : "Sell") : e.exit_reason || "Exit"}${e.position_id === selected ? " · selected" : ""}`,
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

export function markerPixels(spacing: number): number {
  return Math.max(2, Math.min(8, spacing * 0.65));
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
