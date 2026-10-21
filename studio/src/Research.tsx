import { useEffect, useMemo, useRef, useState } from "react";
import {
  createChart,
  CandlestickSeries,
  LineSeries,
  ColorType,
  createSeriesMarkers,
  type UTCTimestamp,
} from "lightweight-charts";
import {
  ArrowLeft,
  ChevronRight,
  Expand,
  ExternalLink,
  Maximize2,
  Minimize2,
  Pause,
  Play,
  X,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import { api, number, type RecordData } from "./api";
// Reuse the existing, regression-tested canonical event projection.
import "../../python/python/observa/static/js/replay-core.js";

declare global {
  interface Window {
    ObservaReplay: any;
  }
}
const timestamp = (value: string) =>
  Math.floor(Date.parse(value) / 1000) as UTCTimestamp;

function Chart({
  bars,
  events,
  cursor,
  equity = false,
  selected,
  select,
}: {
  bars: any[];
  events: any[];
  cursor: number;
  equity?: boolean;
  selected: string | null;
  select: (bar: number) => void;
}) {
  const container = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState("");
  const chartRef = useRef<any>(null);
  const seriesRef = useRef<any>(null);
  const markerRef = useRef<any>(null);
  const selectRef = useRef(select);
  selectRef.current = select;
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
          priceFormat: { type: "price", precision: 5, minMove: 0.00001 },
        });
    chartRef.current = chart;
    seriesRef.current = series;
    if (!equity) markerRef.current = createSeriesMarkers(series, []);
    chart.subscribeClick((param) => {
      if (typeof param.time === "number") {
        const index = bars.findIndex((b) => timestamp(b.time) === param.time);
        if (index >= 0) selectRef.current(index);
      }
    });
    chart.subscribeCrosshairMove((param) => {
      const datum: any = param.seriesData.get(series);
      setHover(
        datum
          ? equity
            ? `Equity ${number(datum.value)}`
            : `O ${number(datum.open, 5)}   H ${number(datum.high, 5)}   L ${number(datum.low, 5)}   C ${number(datum.close, 5)}`
          : "",
      );
    });
    return () => {
      chart.remove();
      chartRef.current = null;
    };
  }, [equity, bars]);
  useEffect(() => {
    if (!seriesRef.current) return;
    const range = chartRef.current.timeScale().getVisibleLogicalRange();
    if (equity) {
      seriesRef.current.setData(
        events
          .filter(
            (e) => e.type === "portfolio_snapshot" && e.bar_index <= cursor,
          )
          .map((e) => ({ time: timestamp(e.timestamp), value: e.equity })),
      );
    } else {
      seriesRef.current.setData(
        bars
          .slice(0, cursor + 1)
          .map((b) => ({ ...b, time: timestamp(b.time) })),
      );
      markerRef.current.setMarkers(
        events
          .filter(
            (e) =>
              (e.type === "position_opened" || e.type === "position_closed") &&
              e.bar_index <= cursor,
          )
          .map((e) => ({
            time: timestamp(bars[e.bar_index].time),
            position: e.type === "position_opened" ? "belowBar" : "aboveBar",
            color: e.position_id === selected ? "#9b5bcb" : "#178363",
            shape: e.type === "position_opened" ? "arrowUp" : "arrowDown",
            text:
              e.position_id === selected
                ? e.type === "position_opened"
                  ? "Entry"
                  : "Exit"
                : "",
          })),
      );
    }
    if (range) chartRef.current.timeScale().setVisibleLogicalRange(range);
    else chartRef.current.timeScale().fitContent();
  }, [bars, events, cursor, equity, selected]);
  return (
    <div className="chart-wrap">
      <div className="chart-readout">
        {hover ||
          (equity
            ? "Canonical end-of-bar equity"
            : "Price · click a bar to inspect")}
      </div>
      <div ref={container} style={{ height: 300, width: "100%" }} />
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
      180,
    );
    return () => clearInterval(timer);
  }, [playing, payload]);
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
                onClick={() => {
                  setSelected(p.position_id);
                  setCursor(p.closed_bar ?? p.opened_bar);
                }}
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    setSelected(p.position_id);
                    setCursor(p.closed_bar ?? p.opened_bar);
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
                  <a
                    href={`/legacy/${job.id}`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Original replay & drawings <ExternalLink size={13} />
                  </a>
                </div>
                {payload.bars.length > 0 ? (
                  <>
                    <Chart
                      bars={payload.bars}
                      events={payload.events}
                      cursor={cursor}
                      selected={selected}
                      select={setCursor}
                    />
                    <div className="playback">
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
                <a
                  className="wide-action"
                  href={`/legacy/${job.id}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  Open original replay <ExternalLink size={15} />
                </a>
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
