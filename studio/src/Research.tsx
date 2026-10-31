import { useEffect, useMemo, useRef, useState } from "react";
import {
  createChart,
  CandlestickSeries,
  LineSeries,
  ColorType,
  type UTCTimestamp,
} from "lightweight-charts";
import {
  ArrowLeft,
  ChevronRight,
  Expand,
  Maximize2,
  Minimize2,
  Pause,
  Play,
  X,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import * as LC from "lightweight-charts";
import {
  executionMarkers,
  replayDelays,
  tradeRange,
  indicatorSamples,
} from "./replay";
import { CompactMarkers } from "./CompactMarkers";
import { api, number, type RecordData } from "./api";
// Reuse the existing, regression-tested canonical event projection.
import "../../python/python/observa/static/js/replay-core.js";
import "../../python/python/observa/static/js/drawing-state.js";
import "../../python/python/observa/static/js/drawing-renderer.js";

declare global {
  interface Window {
    ObservaReplay: any;
    ObservaDrawings: any;
    ObservaDrawingRenderer: any;
  }
}
const timestamp = (value: string) =>
  Math.floor(Date.parse(value) / 1000) as UTCTimestamp;

const EMPTY: any[] = [];

function Chart({
  bars,
  events,
  cursor,
  equity = false,
  selected,
  select,
  drawings = EMPTY,
  annotations = true,
  markers = true,
  levels = EMPTY,
  position,
  following = false,
  unfollow,
  focus = 0,
  fit = 0,
  precision = 5,
  instrument = "",
  report,
}: {
  bars: any[];
  events: any[];
  cursor: number;
  equity?: boolean;
  selected: string | null;
  select: (bar: number) => void;
  drawings?: any[];
  annotations?: boolean;
  markers?: boolean;
  levels?: any[];
  position?: any;
  following?: boolean;
  unfollow?: () => void;
  focus?: number;
  fit?: number;
  precision?: number;
  instrument?: string;
  report?: any;
}) {
  const container = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<any>(null);
  const [showBalance, setShowBalance] = useState(true);
  const [showDrawdown, setShowDrawdown] = useState(true);
  const balanceRef = useRef<any>(null),
    connectorRef = useRef<any>(null);
  const hoverContext = useRef<any>(null);
  const chartRef = useRef<any>(null),
    seriesRef = useRef<any>(null),
    markerRef = useRef<any>(null);
  const layerRef = useRef<any>(null),
    highlightRef = useRef<any>(null),
    priceLines = useRef<any[]>([]);
  const selectRef = useRef(select),
    unfollowRef = useRef(unfollow);
  const lastFocus = useRef<string>(""),
    lastFit = useRef(-1);
  selectRef.current = select;
  unfollowRef.current = unfollow;
  const times = useMemo(() => bars.map((b) => timestamp(b.time)), [bars]);
  const drawingState = useMemo(
    () => window.ObservaDrawings.fold(drawings, cursor, times),
    [drawings, cursor, times],
  );
  const legend = window.ObservaDrawings.summary(drawingState);
  const drawdownStart = report?.max_drawdown_start
    ? timestamp(report.max_drawdown_start)
    : null;
  const drawdownEnd = report?.max_drawdown_end
    ? timestamp(report.max_drawdown_end)
    : null;
  const drawdownVisible =
    drawdownStart != null &&
    drawdownEnd != null &&
    drawdownEnd <= times[cursor];
  hoverContext.current = {
    cursor,
    drawingState,
    annotations,
    events,
    markers,
    showBalance,
  };
  const clearHover = () => setHover(null);
  const updateHover = (param: any) => {
    const context = hoverContext.current;
    const barIndex =
      typeof param.time === "number" ? times.indexOf(param.time) : -1;
    if (!param.point || barIndex < 0 || barIndex > context.cursor) {
      clearHover();
      return;
    }
    const snapshot = context.events.find(
      (e: any) => e.type === "portfolio_snapshot" && e.bar_index === barIndex,
    );
    setHover({
      barIndex,
      bar: bars[barIndex],
      x: param.point.x,
      y: param.point.y,
      width: container.current?.clientWidth || 300,
      snapshot,
      indicators: context.annotations
        ? indicatorSamples(context.drawingState, param.time)
        : [],
      trades: context.markers
        ? context.events.filter(
            (e: any) =>
              e.bar_index === barIndex &&
              ["position_opened", "position_closed"].includes(e.type),
          )
        : [],
      signals: context.annotations
        ? context.drawingState.markers.filter((m: any) => m.time === param.time)
        : [],
    });
  };
  useEffect(() => {
    const chart = createChart(container.current!, {
      autoSize: true,
      height: 300,
      layout: {
        background: { type: ColorType.Solid, color: "#ffffff" },
        textColor: "#768079",
        fontFamily: "system-ui",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: "#f1f3ef" },
        horzLines: { color: "#f1f3ef" },
      },
      rightPriceScale: { borderColor: "#e8ece6" },
      timeScale: { borderColor: "#e8ece6", timeVisible: true },
      crosshair: { mode: 0 },
    });
    const series = equity
      ? chart.addSeries(LineSeries, {
          color: "#178363",
          lineWidth: 2,
          priceLineVisible: false,
        })
      : chart.addSeries(CandlestickSeries, {
          upColor: "#288c71",
          downColor: "#c36c60",
          wickUpColor: "#288c71",
          wickDownColor: "#c36c60",
          borderVisible: false,
          priceFormat: {
            type: "price",
            precision,
            minMove: Math.pow(10, -precision),
          },
        });
    chartRef.current = chart;
    seriesRef.current = series;
    layerRef.current = window.ObservaDrawingRenderer.create(chart, series, LC);
    if (equity) {
      balanceRef.current = chart.addSeries(LineSeries, {
        color: "#808aa4",
        lineWidth: 1,
        lineStyle: LC.LineStyle.Dashed,
        priceLineVisible: false,
      });
    } else {
      markerRef.current = new CompactMarkers();
      series.attachPrimitive(markerRef.current);
    }
    chart.subscribeClick((param) => {
      if (typeof param.time === "number") {
        const i = times.indexOf(param.time as UTCTimestamp);
        if (i >= 0) selectRef.current(i);
      }
    });
    chart.subscribeCrosshairMove(updateHover);
    const host = container.current!;
    const manual = () => unfollowRef.current?.();
    host.addEventListener("wheel", manual, { passive: true });
    host.addEventListener("pointerdown", manual);
    lastFocus.current = "";
    lastFit.current = -1;
    return () => {
      host.removeEventListener("wheel", manual);
      host.removeEventListener("pointerdown", manual);
      chart.remove();
      layerRef.current = null;
      highlightRef.current = null;
      priceLines.current = [];
      connectorRef.current = null;
      balanceRef.current = null;
    };
  }, [bars, equity, precision]);
  useEffect(() => {
    const chart = chartRef.current,
      series = seriesRef.current;
    if (!series) return;
    setHover(null);
    const range = chart.timeScale().getVisibleLogicalRange();
    if (equity) {
      if (highlightRef.current)
        layerRef.current.removePrimitive(highlightRef.current);
      highlightRef.current =
        showDrawdown && drawdownVisible
          ? layerRef.current.createPrimitive({
              type: "region",
              time_start: report.max_drawdown_start,
              time_end: report.max_drawdown_end,
              color: "#c35449",
              opacity: 0.08,
              label: "Maximum drawdown",
            })
          : null;
      balanceRef.current.applyOptions({ visible: showBalance });
      balanceRef.current.setData(
        events
          .filter(
            (e) => e.type === "portfolio_snapshot" && e.bar_index <= cursor,
          )
          .map((e) => ({ time: timestamp(e.timestamp), value: e.balance })),
      );
      series.setData(
        events
          .filter(
            (e) => e.type === "portfolio_snapshot" && e.bar_index <= cursor,
          )
          .map((e) => ({ time: timestamp(e.timestamp), value: e.equity })),
      );
    } else {
      const candles = bars.slice(0, cursor + 1).map((b, i) => {
        const color = annotations
          ? drawingState.barColors[times[i]]
          : undefined;
        return {
          ...b,
          time: times[i],
          ...(color ? { color, wickColor: color, borderColor: color } : {}),
        };
      });
      series.setData(candles);
      const layer = layerRef.current;
      layer.setCandles(candles);
      layer.apply(drawingState, { visible: annotations });
      const canonical = markers
        ? executionMarkers(events, bars, cursor, selected)
        : [];
      const strategy = layer.drawingMarkersFor(drawingState, annotations);
      markerRef.current.setData([...canonical, ...strategy], candles);
      if (connectorRef.current) layer.removePrimitive(connectorRef.current);
      connectorRef.current =
        position && position.closed_bar != null && position.closed_bar <= cursor
          ? layer.createPrimitive({
              type: "line",
              x1: bars[position.opened_bar].time,
              y1: position.entry_price,
              x2: bars[position.closed_bar].time,
              y2: position.exit_price,
              color: "#9953c4",
              line_style: "dashed",
              width: 1,
            })
          : null;
      for (const line of priceLines.current) series.removePriceLine(line);
      priceLines.current = [];
      for (const p of levels)
        for (const [field, title, color] of [
          ["entry_price", "Entry", "#448a72"],
          ["stop_loss", "SL", "#c35449"],
          ["take_profit", "TP", "#4386b4"],
        ]) {
          if (typeof p[field] === "number")
            priceLines.current.push(
              series.createPriceLine({
                price: p[field],
                title,
                color,
                lineWidth: 1,
                lineStyle: LC.LineStyle.Dashed,
                axisLabelVisible: true,
              }),
            );
        }
      if (highlightRef.current) layer.removePrimitive(highlightRef.current);
      highlightRef.current =
        position && position.opened_bar <= cursor
          ? layer.createPrimitive({
              type: "region",
              time_start: bars[position.opened_bar].time,
              time_end:
                bars[Math.min(position.closed_bar ?? cursor, cursor)].time,
              color: "#9953c4",
              opacity: 0.12,
              label: "Selected trade",
            })
          : null;
    }
    const focusKey = `${selected}:${focus}`;
    if (
      position &&
      position.opened_bar <= cursor &&
      lastFocus.current !== focusKey
    ) {
      chart.timeScale().setVisibleLogicalRange(tradeRange(position, cursor));
      chart.priceScale("right").applyOptions({ autoScale: true });
    } else if (lastFit.current !== fit) chart.timeScale().fitContent();
    else if (following)
      chart.timeScale().setVisibleLogicalRange({
        from: Math.max(-1, cursor - 70),
        to: cursor + 5,
      });
    else if (range) chart.timeScale().setVisibleLogicalRange(range);
    else chart.timeScale().fitContent();
    lastFocus.current = focusKey;
    lastFit.current = fit;
  }, [
    bars,
    events,
    cursor,
    equity,
    selected,
    drawingState,
    annotations,
    markers,
    levels,
    position,
    following,
    focus,
    fit,
    showBalance,
    showDrawdown,
    drawdownVisible,
    report,
  ]);
  return (
    <div className="chart-wrap">
      <div className="chart-readout">
        {equity
          ? "Canonical end-of-bar equity"
          : `${instrument || "Price"} · hover to inspect · click to select a bar`}
        {equity && (
          <label className="balance-toggle">
            <input
              type="checkbox"
              checked={showBalance}
              onChange={(e) => setShowBalance(e.target.checked)}
            />{" "}
            Balance
          </label>
        )}
      </div>
      <div className="chart-surface" onMouseLeave={clearHover}>
        <div ref={container} style={{ height: 300, width: "100%" }} />
        {hover && (
          <div
            className="chart-tooltip"
            role="tooltip"
            aria-label={equity ? "Account values" : "Chart values"}
            style={{
              left: Math.max(
                4,
                Math.min(
                  hover.x + 16,
                  hover.width - Math.min(270, hover.width - 8),
                ),
              ),
              top: hover.y > 150 ? 12 : undefined,
              bottom: hover.y <= 150 ? 12 : undefined,
            }}
          >
            <strong>
              {new Date(hover.bar.time)
                .toISOString()
                .replace("T", " ")
                .replace(".000Z", " UTC")}
            </strong>
            <small>Bar {hover.barIndex + 1}</small>
            <dl>
              {(equity
                ? [
                    ["Equity", hover.snapshot?.equity],
                    ...(showBalance
                      ? [["Balance", hover.snapshot?.balance]]
                      : []),
                  ]
                : [
                    ["Open", hover.bar.open],
                    ["High", hover.bar.high],
                    ["Low", hover.bar.low],
                    ["Close", hover.bar.close],
                    ["Volume", hover.bar.volume],
                  ]
              ).map(([label, value]) => (
                <div key={label}>
                  <dt>{label}</dt>
                  <dd>
                    {number(
                      value,
                      equity ? 2 : label === "Volume" ? 2 : precision,
                    )}
                  </dd>
                </div>
              ))}
              {!equity &&
                hover.indicators.map((s: any) => (
                  <div key={s.id}>
                    <dt style={{ color: s.color }}>{s.label}</dt>
                    <dd>{number(s.value, precision)}</dd>
                  </div>
                ))}
            </dl>
            {!equity && hover.trades.length > 0 && (
              <div className="tooltip-trades">
                <b>{hover.trades.length} execution event(s)</b>
                {hover.trades.slice(0, 6).map((e: any) => (
                  <p key={e.event_seq}>
                    {e.type === "position_opened"
                      ? `${e.side} entry`
                      : `${e.side} exit · ${e.exit_reason || "Exit"}`}{" "}
                    @{" "}
                    {number(
                      e.type === "position_opened"
                        ? e.entry_price
                        : e.exit_price,
                      precision,
                    )}
                    <small>
                      {e.position_id?.slice(0, 8)}
                      {e.reason ? ` · ${e.reason}` : ""}
                    </small>
                  </p>
                ))}
                {hover.trades.length > 6 && (
                  <small>
                    All events are available in the bar inspector below.
                  </small>
                )}
              </div>
            )}
            {!equity &&
              hover.signals.map((m: any) => (
                <p key={m.id} style={{ color: m.color }}>
                  {m.text || "Strategy marker"}
                </p>
              ))}
          </div>
        )}
      </div>
      {equity && (
        <div className="replay-options">
          <label title="Uses the maximum-drawdown period recorded by the engine. Available after replay reaches that period.">
            <input
              type="checkbox"
              checked={showDrawdown}
              disabled={!drawdownVisible}
              onChange={(e) => setShowDrawdown(e.target.checked)}
            />{" "}
            Maximum drawdown
          </label>
          <button
            disabled={!drawdownVisible}
            onClick={() => {
              setShowDrawdown(true);
              chartRef.current
                .timeScale()
                .setVisibleRange({
                  from: drawdownStart,
                  to: Math.max(drawdownEnd!, drawdownStart! + 1),
                });
            }}
          >
            Inspect drawdown
          </button>
          <button onClick={() => chartRef.current.timeScale().fitContent()}>
            Fit account chart
          </button>
        </div>
      )}
      {!equity && annotations && (
        <div className="indicator-legend" aria-label="Strategy indicators">
          {legend.series.map((s: any) => (
            <span
              key={s.id}
              tabIndex={0}
              title={`${s.label} · ${s.pane === "separate" ? "Separate pane" : "Price overlay"}. Hover the chart for recorded values at each bar. Missing samples are unavailable, never interpolated.`}
              style={{ color: s.color }}
            >
              {s.label} · {s.points} points
            </span>
          ))}
          {!legend.series.length && (
            <span>No indicator series recorded through this bar.</span>
          )}
          {legend.primitiveCount > 0 && (
            <span>{legend.primitiveCount} drawings</span>
          )}
        </div>
      )}
    </div>
  );
}

export function Metrics({
  metrics,
  compact = false,
}: {
  metrics: any;
  compact?: boolean;
}) {
  const definitions = compact
    ? [
        ["total_return_pct", "Return", "%"],
        ["max_drawdown_pct", "Max drawdown", "%"],
        ["total_trades", "Closed trades", ""],
      ]
    : [
        ["final_equity", "Final equity", ""],
        ["total_return_pct", "Total return", "%"],
        ["max_drawdown_pct", "Max drawdown", "%"],
        ["total_trades", "Closed trades", ""],
        ["win_rate_pct", "Win rate", "%"],
        ["profit_factor", "Profit factor", ""],
        ["sharpe_ratio", "Sharpe ratio", ""],
        ["total_costs", "Total costs", ""],
      ];
  return (
    <div className={compact ? "metric-row" : "metric-grid"}>
      {definitions.map(([key, title, unit]) => (
        <div
          className="metric"
          key={key}
          title={metrics?.unavailable?.[key] || ""}
        >
          <span>{title}</span>
          <strong>
            {number(metrics?.[key])}
            {metrics?.[key] != null ? unit : ""}
          </strong>
        </div>
      ))}
    </div>
  );
}

export default function Research({
  job,
  close,
  ask,
}: {
  job: RecordData;
  close: () => void;
  ask: (text: string) => void;
}) {
  const [payload, setPayload] = useState<any>(null);
  const [positions, setPositions] = useState<any[]>([]);
  const [rejections, setRejections] = useState<any[]>([]);
  const [error, setError] = useState("");
  const [tab, setTab] = useState("overview");
  const [full, setFull] = useState(false);
  const [tradesFull, setTradesFull] = useState(false);
  const [cursor, setCursor] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState("1×");
  const [annotations, setAnnotations] = useState(true);
  const [markers, setMarkers] = useState(true);
  const [showLevels, setShowLevels] = useState(true);
  const [following, setFollowing] = useState(true);
  const [focus, setFocus] = useState(0);
  const [fit, setFit] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  useEffect(() => {
    let cancelled = false;
    Promise.all([
      api(`/experiments/${job.id}/replay`),
      api(`/experiments/${job.id}/trades`),
    ])
      .then(([data, inspection]) => {
        if (cancelled) return;
        setPayload(data);
        setCursor(data.bars.length - 1);
        setPositions(inspection.positions);
        setRejections(inspection.rejections);
      })
      .catch((e) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [job.id]);
  useEffect(() => {
    if (!playing || !payload) return;
    const timer = setInterval(
      () =>
        setCursor((c) => {
          if (c >= payload.bars.length - 1) {
            setPlaying(false);
            return c;
          }
          return c + 1;
        }),
      replayDelays[speed],
    );
    return () => clearInterval(timer);
  }, [playing, payload, speed]);
  useEffect(() => {
    const escape = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setFull(false);
        setTradesFull(false);
      }
    };
    document.addEventListener("keydown", escape);
    return () => document.removeEventListener("keydown", escape);
  }, []);
  const index = useMemo(
    () => (payload ? window.ObservaReplay.indexEvents(payload.events) : null),
    [payload],
  );
  const view = useMemo(
    () =>
      payload
        ? window.ObservaReplay.stateThrough(
            payload.events,
            index.endEventOfBar[cursor],
          )
        : null,
    [payload, index, cursor],
  );
  const position = positions.find((p) => p.position_id === selected);
  const selectTrade = (p: any) => {
    setPlaying(false);
    setSelected(p.position_id);
    setCursor(p.closed_bar ?? p.opened_bar);
    setTab("replay");
    setTradesFull(false);
    setFollowing(false);
    setFocus((n) => n + 1);
  };
  const seek = (bar: number) => {
    setPlaying(false);
    setCursor(bar);
  };
  const selectedEvents =
    payload?.events.filter(
      (e: any) =>
        e.position_id === selected ||
        (position &&
          (e.order_seq === position.opening_order_seq ||
            e.order_seq === position.closing_order_seq)),
    ) || [];
  const visiblePositions = positions.filter((p) =>
    `${p.side} ${p.position_id} ${p.exit_reason || ""} ${p.status}`
      .toLowerCase()
      .includes(query.toLowerCase()),
  );
  const tradeTable = (
    <div className={tradesFull ? "trade-overlay" : ""}>
      <div className="section-heading">
        <div>
          <h3>Trade explorer</h3>
          <p>{positions.length} positions · canonical execution history</p>
        </div>
        <button
          className="icon-button"
          title={
            tradesFull ? "Exit full-screen trades" : "Expand trade explorer"
          }
          onClick={() => setTradesFull(!tradesFull)}
        >
          {tradesFull ? <Minimize2 size={17} /> : <Expand size={17} />}
        </button>
      </div>
      <input
        className="trade-search"
        placeholder="Filter by side, ticket or exit reason…"
        aria-label="Filter trades"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Position</th>
              <th>Side / size</th>
              <th>Entry</th>
              <th>Exit</th>
              <th>Net P&L</th>
              <th>Exit reason</th>
            </tr>
          </thead>
          <tbody>
            {visiblePositions.map((p, i) => (
              <tr
                key={p.position_id}
                className={selected === p.position_id ? "selected" : ""}
                onClick={() => selectTrade(p)}
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    selectTrade(p);
                  }
                }}
              >
                <td>
                  <b>#{i + 1}</b>
                  <small>{p.position_id.slice(0, 8)}</small>
                </td>
                <td>
                  {p.side}
                  <small>{number(p.quantity_lots, 4)} lots</small>
                </td>
                <td>
                  {number(p.entry_price, 5)}
                  <small>Bar {p.opened_bar}</small>
                </td>
                <td>
                  {number(p.exit_price, 5)}
                  <small>
                    {p.closed_bar == null
                      ? "Still open"
                      : `Bar ${p.closed_bar}`}
                  </small>
                </td>
                <td
                  className={p.net_realized_pnl < 0 ? "negative" : "positive"}
                >
                  {number(p.net_realized_pnl)}
                </td>
                <td>{p.exit_reason || "Open"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!visiblePositions.length && (
          <p className="empty-small">No positions match this filter.</p>
        )}
      </div>
      {position && (
        <div className="position-detail">
          <div className="section-heading">
            <h3>Position {position.position_id.slice(0, 8)}</h3>
            <button
              className="text-button"
              onClick={() => {
                ask(
                  `Explain position ${position.position_id} in experiment ${job.id}. Use its canonical orders, fills, costs and reasons.`,
                );
                close();
              }}
            >
              Discuss in chat <ChevronRight size={14} />
            </button>
          </div>
          <div className="trade-jumps">
            <button
              onClick={() => {
                setPlaying(false);
                setFollowing(false);
                setFocus((n) => n + 1);
                setCursor(position.opened_bar);
                setTab("replay");
                setTradesFull(false);
              }}
            >
              Jump to entry
            </button>
            <button
              disabled={position.closed_bar == null}
              onClick={() => {
                setPlaying(false);
                setFollowing(false);
                setFocus((n) => n + 1);
                setCursor(position.closed_bar);
                setTab("replay");
                setTradesFull(false);
              }}
            >
              Jump to exit
            </button>
          </div>
          {selectedEvents.map((e: any) => (
            <details className="event-detail" key={e.event_seq}>
              <summary>
                {e.type.replaceAll("_", " ")}{" "}
                <small>
                  event {e.event_seq}
                  {e.bar_index != null ? ` · bar ${e.bar_index}` : ""}
                  {e.reason ? ` · ${e.reason}` : ""}
                </small>
              </summary>
              <pre>{JSON.stringify(e, null, 2)}</pre>
            </details>
          ))}
        </div>
      )}
    </div>
  );
  return (
    <aside
      className={`research ${full ? "fullscreen" : ""}`}
      aria-label="Research canvas"
    >
      <header className="canvas-header">
        <div className="canvas-title">
          <span className="eyebrow">RESEARCH CANVAS</span>
          <h2>{job.title}</h2>
        </div>
        <button
          className="icon-button"
          title={full ? "Exit full-screen canvas" : "Expand research canvas"}
          onClick={() => setFull(!full)}
        >
          {full ? <Minimize2 size={18} /> : <Maximize2 size={18} />}
        </button>
        <button
          className="icon-button"
          title="Close research canvas"
          onClick={close}
        >
          <X size={18} />
        </button>
      </header>
      <nav className="tabs">
        {["overview", "replay", "trades", "evidence"].map((t) => (
          <button
            className={tab === t ? "active" : ""}
            key={t}
            onClick={() => setTab(t)}
          >
            {t[0].toUpperCase() + t.slice(1)}
          </button>
        ))}
      </nav>
      <div className="canvas-content">
        {error && <div className="error">{error}</div>}
        {!payload && !error && (
          <div className="empty-small">Loading canonical result…</div>
        )}
        {payload && (
          <>
            {tab === "overview" && (
              <>
                <div className="section-heading">
                  <h3>Run performance</h3>
                  <span className="verified">Engine result</span>
                </div>
                <Metrics metrics={payload.metrics} />
                <h3 className="chart-heading">
                  Equity curve{" "}
                  <span>{payload.metrics?.assumptions?.currency}</span>
                </h3>
                <Chart
                  bars={payload.bars}
                  events={payload.events}
                  report={payload.metrics}
                  cursor={payload.bars.length - 1}
                  equity
                  selected={selected}
                  select={(c) => {
                    setCursor(c);
                    setTab("replay");
                  }}
                />
                {(payload.metrics?.warnings || []).map((w: string) => (
                  <p className="note" key={w}>
                    {w}
                  </p>
                ))}
                {payload.metrics?.open_positions_remaining > 0 && (
                  <p className="note">
                    {payload.metrics.open_positions_remaining} position(s)
                    remain open. Equity includes unrealised P&L.
                  </p>
                )}
                <button
                  className="wide-action"
                  onClick={() => setTab("replay")}
                >
                  Explore price and replay <ChevronRight size={16} />
                </button>
                {tradeTable}
              </>
            )}
            {tab === "replay" && (
              <>
                <div className="section-heading">
                  <h3>Price replay</h3>
                </div>
                {payload.bars.length > 0 ? (
                  <>
                    <Chart
                      bars={payload.bars}
                      events={payload.events}
                      report={payload.metrics}
                      cursor={cursor}
                      selected={selected}
                      select={seek}
                      precision={payload.run?.price_decimals ?? 5}
                      instrument={[payload.run?.symbol, payload.run?.interval]
                        .filter(Boolean)
                        .join(" · ")}
                      drawings={payload.drawings || []}
                      annotations={annotations}
                      markers={markers}
                      levels={
                        showLevels
                          ? [...view.positions.values()].filter(
                              (p: any) => p.open,
                            )
                          : []
                      }
                      position={position}
                      following={following}
                      unfollow={() => setFollowing(false)}
                      focus={focus}
                      fit={fit}
                    />
                    <div className="replay-options">
                      <label>
                        <input
                          type="checkbox"
                          checked={annotations}
                          onChange={(e) => setAnnotations(e.target.checked)}
                        />{" "}
                        Indicators & drawings
                      </label>
                      <label>
                        <input
                          type="checkbox"
                          checked={markers}
                          onChange={(e) => setMarkers(e.target.checked)}
                        />{" "}
                        Trade markers
                      </label>
                      <label>
                        <input
                          type="checkbox"
                          checked={showLevels}
                          onChange={(e) => setShowLevels(e.target.checked)}
                        />{" "}
                        Entry / SL / TP
                      </label>
                      <button
                        aria-pressed={following}
                        onClick={() => setFollowing(!following)}
                      >
                        Follow replay
                      </button>
                      <button
                        onClick={() => {
                          setFollowing(false);
                          setFit((n) => n + 1);
                        }}
                      >
                        Fit chart
                      </button>
                    </div>
                    <div className="playback">
                      <button aria-label="First bar" onClick={() => seek(0)}>
                        ↤
                      </button>
                      <button
                        aria-label="Previous bar"
                        disabled={cursor === 0}
                        onClick={() => seek(cursor - 1)}
                      >
                        ←
                      </button>
                      <button
                        className="icon-button"
                        title={playing ? "Pause replay" : "Play replay"}
                        onClick={() => {
                          if (cursor === payload.bars.length - 1) setCursor(0);
                          setPlaying(!playing);
                        }}
                      >
                        {playing ? <Pause size={16} /> : <Play size={16} />}
                      </button>
                      <button
                        aria-label="Next bar"
                        disabled={cursor === payload.bars.length - 1}
                        onClick={() => seek(cursor + 1)}
                      >
                        →
                      </button>
                      <button
                        aria-label="Last bar"
                        onClick={() => seek(payload.bars.length - 1)}
                      >
                        ↦
                      </button>
                      <select
                        aria-label="Replay speed"
                        value={speed}
                        onChange={(e) => setSpeed(e.target.value)}
                      >
                        {Object.keys(replayDelays).map((s) => (
                          <option key={s}>{s}</option>
                        ))}
                      </select>
                      <input
                        aria-label="Replay bar"
                        type="range"
                        min={0}
                        max={payload.bars.length - 1}
                        value={cursor}
                        onChange={(e) => {
                          setPlaying(false);
                          setCursor(+e.target.value);
                        }}
                      />
                      <span>
                        {cursor + 1} / {payload.bars.length}
                      </span>
                    </div>
                    <p className="muted">
                      {payload.bars[cursor]?.time} · snapshots through bar{" "}
                      {cursor}
                    </p>
                    <div className="metric-row">
                      {[
                        "balance",
                        "equity",
                        "unrealised_pnl",
                        "open_positions",
                      ].map((key) => (
                        <div className="metric" key={key}>
                          <span>{key.replaceAll("_", " ")}</span>
                          <strong>{number(view?.account?.[key])}</strong>
                        </div>
                      ))}
                    </div>
                    <Chart
                      bars={payload.bars}
                      events={payload.events}
                      report={payload.metrics}
                      cursor={cursor}
                      equity
                      selected={selected}
                      select={setCursor}
                    />
                    <details className="event-detail">
                      <summary>
                        Events at this bar ({index.bars[cursor]?.length || 0})
                      </summary>
                      <pre>{JSON.stringify(index.bars[cursor], null, 2)}</pre>
                    </details>
                  </>
                ) : (
                  <p className="note">
                    Source bars are unavailable. Canonical events and metrics
                    remain inspectable.
                  </p>
                )}
                {tradeTable}
              </>
            )}
            {tab === "trades" && tradeTable}
            {tab === "evidence" && (
              <>
                <h3>Reproducibility record</h3>
                <p className="muted">
                  This result was produced from the approved snapshot. Metrics
                  are loaded directly from Observa.
                </p>
                <dl className="evidence">
                  <dt>Experiment</dt>
                  <dd>{job.id}</dd>
                  <dt>Snapshot SHA-256</dt>
                  <dd>{job.snapshot_hash}</dd>
                  <dt>Run directory</dt>
                  <dd>{job.run_dir}</dd>
                </dl>
                <details className="event-detail">
                  <summary>Approved configuration & file hashes</summary>
                  <pre>{JSON.stringify(job.manifest, null, 2)}</pre>
                </details>
                <details className="event-detail">
                  <summary>Strategy source</summary>
                  <pre>{job.source_preview}</pre>
                </details>
                <details className="event-detail">
                  <summary>
                    All canonical metrics & availability reasons
                  </summary>
                  <pre>{JSON.stringify(payload.metrics, null, 2)}</pre>
                </details>
                <details className="event-detail">
                  <summary>Order rejections ({rejections.length})</summary>
                  <pre>{JSON.stringify(rejections, null, 2)}</pre>
                </details>
              </>
            )}
          </>
        )}
      </div>
    </aside>
  );
}

export function Artifact({
  artifact,
  close,
}: {
  artifact: RecordData;
  close: () => void;
}) {
  const [full, setFull] = useState(false);
  const points = artifact.data || [];
  const extent = (key: string) => {
    const values = points.map((p: any) => p[key]);
    const a = Math.min(0, ...values),
      b = Math.max(1, ...values);
    return [a, b];
  };
  const [xmin, xmax] = extent("x"),
    [ymin, ymax] = extent("y"),
    [vmin, vmax] = extent("value");
  const x = (v: number) => 55 + ((v - xmin) / (xmax - xmin)) * 570;
  const y = (v: number) => 330 - ((v - ymin) / (ymax - ymin)) * 290;
  return (
    <aside
      className={`research ${full ? "fullscreen" : ""}`}
      aria-label="Research artifact"
    >
      <header className="canvas-header">
        <div className="canvas-title">
          <span className="eyebrow">RESEARCH ARTIFACT</span>
          <h2>{artifact.title}</h2>
        </div>
        <button
          className="icon-button"
          title="Expand artifact"
          onClick={() => setFull(!full)}
        >
          <Maximize2 size={18} />
        </button>
        <button className="icon-button" title="Close artifact" onClick={close}>
          <X size={18} />
        </button>
      </header>
      <div className="canvas-content">
        <span className="interpretation">Agent-generated interpretation</span>
        <p className="muted">{artifact.description}</p>
        {artifact.kind === "markdown" && (
          <div className="prose">
            <ReactMarkdown>{artifact.text}</ReactMarkdown>
          </div>
        )}
        {artifact.kind === "table" && (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  {artifact.columns.map((c: string, i: number) => (
                    <th key={i}>{c}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {artifact.rows.map((r: any[], i: number) => (
                  <tr key={i}>
                    {r.map((c, j) => (
                      <td key={j}>{String(c ?? "—")}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {artifact.kind === "plot" && (
          <svg
            viewBox="0 0 660 390"
            className="research-plot"
            role="img"
            aria-label={artifact.title}
          >
            <path d="M55 35V330H630" fill="none" stroke="#ccd4ca" />
            <text x="340" y="380" textAnchor="middle">
              {artifact.x_label || "x"}
            </text>
            <text
              x="20"
              y="180"
              transform="rotate(-90 20 180)"
              textAnchor="middle"
            >
              {artifact.y_label || "y"}
            </text>
            {[0, 0.25, 0.5, 0.75, 1].map((f) => (
              <g key={f}>
                <text x="48" y={y(ymin + (ymax - ymin) * f)} textAnchor="end">
                  {number(ymin + (ymax - ymin) * f)}
                </text>
                <text
                  x={x(xmin + (xmax - xmin) * f)}
                  y="350"
                  textAnchor="middle"
                >
                  {number(xmin + (xmax - xmin) * f)}
                </text>
              </g>
            ))}
            {artifact.mark === "line" && (
              <path
                d={points
                  .map(
                    (p: any, i: number) =>
                      `${i ? "L" : "M"}${x(p.x)},${y(p.y)}`,
                  )
                  .join(" ")}
                fill="none"
                stroke="#178363"
                strokeWidth="2"
              />
            )}
            {points.map((p: any, i: number) => (
              <g key={i}>
                <title>{`${artifact.x_label || "x"}: ${p.x}, ${artifact.y_label || "y"}: ${p.y}${p.value != null ? ", value: " + p.value : ""}`}</title>
                {artifact.mark === "bar" ? (
                  <rect
                    x={x(p.x) - Math.min(18, 250 / points.length)}
                    y={Math.min(y(0), y(p.y))}
                    width={Math.min(36, 500 / points.length)}
                    height={Math.abs(y(p.y) - y(0))}
                    fill="#288c71"
                  />
                ) : artifact.mark === "heatmap" ? (
                  <rect
                    x={x(p.x) - 10}
                    y={y(p.y) - 10}
                    width="20"
                    height="20"
                    fill="#178363"
                    opacity={0.15 + (0.85 * (p.value - vmin)) / (vmax - vmin)}
                  />
                ) : (
                  <circle cx={x(p.x)} cy={y(p.y)} r="3" fill="#178363" />
                )}
              </g>
            ))}
          </svg>
        )}
        <details className="event-detail">
          <summary>Artifact data & source experiment references</summary>
          <pre>{JSON.stringify(artifact, null, 2)}</pre>
        </details>
        <button className="text-button" onClick={close}>
          <ArrowLeft size={14} /> Back to conversation
        </button>
      </div>
    </aside>
  );
}
