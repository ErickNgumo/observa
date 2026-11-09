import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  Activity,
  ArrowUp,
  ArrowUpRight,
  BarChart3,
  Check,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  Code2,
  Folder,
  FolderPlus,
  History,
  LoaderCircle,
  MessageSquare,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  Search,
  ShieldCheck,
  Sparkles,
  Square,
  X,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import {
  api,
  authenticate,
  canStop,
  type RecordData,
  type Snapshot,
  upsert,
} from "./api";
import Research, { Artifact, Metrics } from "./Research";
import AgentSettings, { commands, permissionLabels } from "./AgentSettings";

const active = (status: string) =>
  ["running", "connecting", "stopping"].includes(status);
function Markdown({ text }: { text: string }) {
  return (
    <div className="prose">
      <ReactMarkdown
        components={{
          a: (props) =>
            props.href?.startsWith("/") ? (
              <code title={`Local file: ${props.href}`}>{props.children}</code>
            ) : (
              <a {...props} target="_blank" rel="noreferrer" />
            ),
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}

function Tool({ item, connected }: { item: RecordData; connected: boolean }) {
  if (["reasoning", "plan"].includes(item.type)) {
    const text = item.text || (item.summary || []).join("\n");
    return text ? (
      <details className="tool">
        <summary>
          <Sparkles size={14} /> Research notes <ChevronDown size={13} />
        </summary>
        <Markdown text={text} />
      </details>
    ) : null;
  }
  const title =
    item.type === "commandExecution"
      ? item.command
      : item.type === "mcpToolCall"
        ? item.tool?.replaceAll("_", " ")
        : item.type === "fileChange"
          ? "Updated project files"
          : item.type;
  return (
    <details className="tool">
      <summary>
        {item.status === "running" && connected ? (
          <LoaderCircle className="spin" size={14} />
        ) : (
          <Code2 size={14} />
        )}
        <span>{title}</span>
        {item.status === "interrupted" && <small>Interrupted</small>}
        {item.status === "running" && !connected && (
          <small>Status unknown</small>
        )}
        <ChevronDown size={13} />
      </summary>
      <pre>{item.aggregatedOutput || JSON.stringify(item, null, 2)}</pre>
    </details>
  );
}

function Approval({
  approval,
  item,
  act,
  providerLabel,
}: {
  approval: RecordData;
  item?: RecordData;
  act: (path: string, body: any) => Promise<void>;
  providerLabel: string;
}) {
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const question = approval.method === "item/tool/requestUserInput";
  const mcp = approval.method === "mcpServer/elicitation/request";
  const formProperties = mcp
    ? approval.params.requestedSchema?.properties || {}
    : {};
  const unsupported =
    mcp &&
    (approval.params.mode !== "form" || Object.keys(formProperties).length > 0);
  const decide = async (approved: boolean, choice?: any) => {
    setBusy(true);
    try {
      await act(`/approvals/${approval.id}`, {
        approved,
        answers,
        ...(choice
          ? { decision: choice.decision, scope: choice.scope || "turn" }
          : {}),
      });
    } finally {
      setBusy(false);
    }
  };
  if (approval.status !== "pending")
    return (
      <div className="resolved-approval">
        <ShieldCheck size={13} />{" "}
        {question ? "Input request" : `${providerLabel} permission`} ·{" "}
        {approval.status}
      </div>
    );
  return (
    <div className="approval">
      <div className="card-title">
        <ShieldCheck size={19} />
        <div>
          <h3>
            {question
              ? `${providerLabel} needs your input`
              : mcp
                ? "Research tool permission"
                : "Permission requested"}
          </h3>
          <p>
            {approval.params.message ||
              approval.params.reason ||
              `Review this action before allowing ${providerLabel} to continue.`}
          </p>
        </div>
      </div>
      {question ? (
        approval.params.questions?.map((q: any) => (
          <label className="question" key={q.id}>
            {q.question}
            {q.options?.length ? (
              <select
                value={answers[q.id] || ""}
                onChange={(e) =>
                  setAnswers({ ...answers, [q.id]: e.target.value })
                }
              >
                <option value="">Choose an answer</option>
                {q.options.map((o: any) => (
                  <option key={o.label} value={o.label}>
                    {o.label} — {o.description}
                  </option>
                ))}
              </select>
            ) : null}
            <input
              placeholder="Your answer"
              value={answers[q.id] || ""}
              onChange={(e) =>
                setAnswers({ ...answers, [q.id]: e.target.value })
              }
            />
          </label>
        ))
      ) : (
        <>
          {item?.changes ? (
            item.changes.map((change: any) => (
              <details className="event-detail" key={change.path} open>
                <summary>
                  {change.kind.type}: {change.path}
                </summary>
                <pre>{change.diff}</pre>
              </details>
            ))
          ) : mcp ? (
            <>
              <p className="muted">{approval.params._meta?.tool_description}</p>
              <details className="event-detail">
                <summary>Tool arguments</summary>
                <pre>
                  {JSON.stringify(
                    approval.params._meta?.tool_params || {},
                    null,
                    2,
                  )}
                </pre>
              </details>
              {unsupported && (
                <p className="error">
                  This interactive tool form is not supported yet. Decline it
                  and continue in chat.
                </p>
              )}
            </>
          ) : (
            <pre className="command">
              {approval.params.command ||
                JSON.stringify(
                  approval.params.permissions || approval.params,
                  null,
                  2,
                )}
            </pre>
          )}
          <p className="note">
            Review requested paths and the scope of each permission before
            approving.
          </p>
        </>
      )}
      <div className="card-actions">
        {approval.choices?.length ? (
          approval.choices.map((choice: any, i: number) => (
            <div key={i} className="approval-choice">
              {typeof choice.decision === "object" && (
                <pre>{JSON.stringify(choice.decision, null, 2)}</pre>
              )}
              <button disabled={busy} onClick={() => decide(false, choice)}>
                {choice.label}
              </button>
            </div>
          ))
        ) : (
          <>
            {!question && (
              <button disabled={busy} onClick={() => decide(false)}>
                Decline
              </button>
            )}
            <button
              className="primary"
              disabled={
                busy ||
                unsupported ||
                (question &&
                  approval.params.questions?.some(
                    (q: any) => !answers[q.id]?.trim(),
                  ))
              }
              onClick={() => decide(true)}
            >
              {question ? "Send answers" : "Allow once"} <Check size={15} />
            </button>
          </>
        )}
      </div>
    </div>
  );
}

function Experiment({
  job,
  open,
  act,
}: {
  job: RecordData;
  open: () => void;
  act: (path: string, body: any) => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const decide = async (approved: boolean) => {
    setBusy(true);
    try {
      await act(`/experiments/${job.id}/decision`, {
        approved,
        snapshot_hash: job.snapshot_hash,
      });
    } finally {
      setBusy(false);
    }
  };
  return (
    <div
      className={`experiment-card ${job.status === "awaiting_approval" ? "approval" : ""}`}
    >
      <div className="card-title">
        <div className="experiment-icon">
          <BarChart3 size={21} />
        </div>
        <div>
          <span className="eyebrow">
            {job.status === "completed" ? "BACKTEST RESULT" : "EXPERIMENT"}
          </span>
          <h3>{job.title}</h3>
        </div>
        <span className={`status ${job.status}`}>
          {job.status.replaceAll("_", " ")}
        </span>
      </div>
      {job.status === "awaiting_approval" && (
        <>
          <p>Run this strategy with the Observa engine?</p>
          <p className="muted">
            Code and data are snapshotted. Validation and execution run locally
            without network access.
          </p>
          <div className="file-pills">
            <span>{job.manifest.strategy_file}</span>
            <span>{job.manifest.dataset_origin}</span>
          </div>
          <details className="event-detail">
            <summary>Review strategy source</summary>
            <pre>{job.source_preview}</pre>
            {job.source_truncated && (
              <p className="note">
                Preview truncated. Download the complete snapshot file below to
                review it.
              </p>
            )}
          </details>
          <details className="event-detail">
            <summary>Review configuration & snapshot</summary>
            <pre>{JSON.stringify(job.manifest, null, 2)}</pre>
          </details>
          <details className="event-detail">
            <summary>Download exact source, support files & data</summary>
            <ul>
              {Object.keys(job.manifest.hashes).map((file) => (
                <li key={file}>
                  <a
                    href={`/api/experiments/${job.id}/snapshot?file=${encodeURIComponent(file)}`}
                    download
                  >
                    {file}
                  </a>
                </li>
              ))}
            </ul>
          </details>
          <div className="card-actions">
            <button disabled={busy} onClick={() => decide(false)}>
              Decline
            </button>
            <button
              className="primary"
              disabled={busy}
              onClick={() => decide(true)}
            >
              <PlayIcon /> Approve & run
            </button>
          </div>
        </>
      )}
      {job.status === "completed" && (
        <>
          <Metrics metrics={job.metrics} compact />
          <button className="wide-action" onClick={open}>
            <span>
              Explore result <small>Replay, equity and individual trades</small>
            </span>
            <ArrowUpRight size={19} />
          </button>
        </>
      )}
      {["queued", "running"].includes(job.status) && (
        <div className="execution-state">
          <LoaderCircle className="spin" size={16} />
          <span>
            {job.status === "queued"
              ? "Waiting for worker"
              : "Validating and running the approved strategy"}
          </span>
          <button
            className="text-button"
            onClick={() => act(`/experiments/${job.id}/cancel`, {})}
          >
            Cancel
          </button>
        </div>
      )}
      {job.error && (
        <details className="event-detail error" open>
          <summary>Execution could not complete</summary>
          <pre>{job.error}</pre>
          {job.validation && (
            <pre>{JSON.stringify(job.validation, null, 2)}</pre>
          )}
        </details>
      )}
    </div>
  );
}

function PlayIcon() {
  return <ChevronRight size={16} />;
}

export default function App() {
  const [providers, setProviders] = useState<any[]>([]);
  const [newProvider, setNewProvider] = useState("codex");
  const [projects, setProjects] = useState<RecordData[]>([]);
  const [conversations, setConversations] = useState<RecordData[]>([]);
  const [projectId, setProjectId] = useState(
    localStorage.getItem("observa-project") || "",
  );
  const [conversationId, setConversationId] = useState(
    localStorage.getItem("observa-conversation") || "",
  );
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [query, setQuery] = useState("");
  const [input, setInput] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [ready, setReady] = useState(false);
  const [connected, setConnected] = useState(true);
  const [stopping, setStopping] = useState(false);
  const [sidebar, setSidebar] = useState(window.innerWidth > 700);
  const [projectModal, setProjectModal] = useState(false);
  const [settingsSection, setSettingsSection] = useState("");
  const [name, setName] = useState("");
  const [path, setPath] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [selected, setSelected] = useState<{
    type: "experiment" | "artifact";
    id: string;
  } | null>(null);
  const [canvasWidth, setCanvasWidth] = useState(620);
  const scroller = useRef<HTMLDivElement>(null);
  const composer = useRef<HTMLTextAreaElement>(null);
  const pinned = useRef(true);
  const project = projects.find((p) => p.id === projectId);
  const running = active(snapshot?.conversation.status || "");
  const stoppable = canStop(snapshot);
  const selectedProvider =
    snapshot?.provider || providers.find((p) => p.id === newProvider);
  const providerLabel = selectedProvider?.label || "Agent";
  const supports = (capability: string) =>
    Boolean(selectedProvider?.capabilities.includes(capability));

  const refresh = async (search = query) => {
    const state = await api("/state?q=" + encodeURIComponent(search));
    setProjects(state.projects);
    setConversations(state.conversations);
    setProviders(state.providers || []);
    if (!(state.providers || []).some((p: any) => p.installed))
      setNotice(
        "Install a supported coding agent to start research. Saved results remain available.",
      );
    else if (!state.sandbox_available)
      setNotice("Install bubblewrap to enable isolated backtests.");
    if (!state.projects.some((p: RecordData) => p.id === projectId))
      setProjectId(state.projects[0]?.id || "");
    if (
      !ready &&
      !state.conversations.some((c: RecordData) => c.id === conversationId)
    )
      setConversationId("");
  };
  useEffect(() => {
    authenticate()
      .then(() => refresh(""))
      .then(() => setReady(true))
      .catch((e) => setError(e.message));
  }, []);
  useEffect(() => {
    if (!ready) return;
    const timer = setTimeout(
      () => refresh(query).catch((e) => setError(e.message)),
      180,
    );
    return () => clearTimeout(timer);
  }, [query, ready]);
  useEffect(() => {
    localStorage.setItem("observa-project", projectId);
  }, [projectId]);
  useEffect(() => {
    localStorage.setItem("observa-conversation", conversationId);
    setSelected(null);
    setSnapshot(null);
    pinned.current = true;
    if (!conversationId || !ready) return;
    let disposed = false,
      events: EventSource | undefined;
    api(`/conversations/${conversationId}`)
      .then((data) => {
        if (disposed) return;
        setSnapshot(data);
        setProjectId(data.conversation.project);
        events = new EventSource(
          `/api/conversations/${conversationId}/events?after=${data.cursor}`,
        );
        events.onopen = () => setConnected(true);
        events.onerror = () => setConnected(false);
        events.onmessage = (message) => {
          const event = JSON.parse(message.data);
          setSnapshot((old) => {
            if (!old) return old;
            if (event.type === "conversation") {
              setConversations((list) => upsert(list, event.data));
              return { ...old, conversation: event.data };
            }
            const field = (
              {
                item: "items",
                experiment: "experiments",
                approval: "approvals",
                artifact: "artifacts",
              } as const
            )[event.type as "item"];
            if (field)
              return {
                ...old,
                [field]: upsert(old[field], event.data),
                cursor: event.seq,
              };
            if (event.type === "notice") setNotice(event.data.message);
            return old;
          });
        };
      })
      .catch((e) => {
        if (!disposed) {
          setConnected(false);
          setError(e.message);
        }
      });
    return () => {
      disposed = true;
      events?.close();
    };
  }, [conversationId, ready]);
  useEffect(() => {
    if (pinned.current && scroller.current)
      scroller.current.scrollTop = scroller.current.scrollHeight;
  }, [snapshot]);
  const act = async (route: string, body: any) => {
    setError("");
    try {
      await api(route, body);
    } catch (e: any) {
      setError(e.message);
    }
  };
  const stop = async () => {
    if (!conversationId || stopping) return;
    const id = conversationId;
    setStopping(true);
    setError("");
    try {
      await api(`/conversations/${id}/cancel`, {});
      const data = await api(`/conversations/${id}`);
      setSnapshot((old) => (old?.conversation.id === id ? data : old));
      setConversations((list) => upsert(list, data.conversation));
    } catch (e: any) {
      setError(
        `Stop could not be confirmed: ${e.message}. If Studio is unreachable, press Ctrl+C in its terminal, then reopen the launch link.`,
      );
    } finally {
      setStopping(false);
    }
  };
  const newConversation = async (pid = projectId) => {
    setSettingsSection("");
    if (!pid) {
      setProjectModal(true);
      return null;
    }
    setInput("");
    const value = await api("/conversations", {
      project: pid,
      provider: newProvider,
    });
    setConversations((list) => [...list, value]);
    setConversationId(value.id);
    return value.id;
  };
  const createProject = async (event: FormEvent) => {
    event.preventDefault();
    setSubmitting(true);
    try {
      const value = await api("/projects", { name, path });
      setProjects((list) => [...list, value]);
      setProjectId(value.id);
      await newConversation(value.id);
      setProjectModal(false);
      setName("");
      setPath("");
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSubmitting(false);
    }
  };
  const openSettings = async (section: string) => {
    if (!supports(section)) {
      setNotice(
        `${providerLabel} does not expose ${section} controls in this installation.`,
      );
      return;
    }
    if (stoppable) {
      setNotice("Stop active research before changing agent settings.");
      return;
    }
    try {
      if (!conversationId) {
        const id = await newConversation();
        if (!id) return;
        setSettingsSection(section);
        return;
      }
      setSettingsSection(section);
    } catch (e: any) {
      setError(e.message);
    }
  };
  const runCommand = async (command: string) => {
    setInput("");
    if (["model", "mode", "permissions"].includes(command))
      await openSettings(command);
    else if (command === "stop") await stop();
    else if (command === "new") await newConversation();
    else if (command === "status") {
      const c = snapshot?.conversation,
        s = c?.settings || {};
      setNotice(
        `${providerLabel} · ${s.model || c?.model || "Configured default model"} · ${s.effort || "default"} reasoning · ${s.mode || "default"} mode · ${permissionLabels[s.permissions || "cautious"] || s.permissions} · ${c?.status || "New conversation"}${c?.thread_id ? " · Thread " + c.thread_id : ""}`,
      );
    } else
      setNotice(
        "Studio commands: " +
          commands
            .map(([name, description]) => `/${name} — ${description}`)
            .join("; "),
      );
  };
  const send = async (event?: FormEvent) => {
    event?.preventDefault();
    if (input.trim().startsWith("/")) {
      await runCommand(input.trim().slice(1).toLowerCase()).catch((e) =>
        setError(e.message),
      );
      return;
    }
    if (!input.trim() || submitting || stoppable || stopping || !connected)
      return;
    if (!projectId) {
      setProjectModal(true);
      return;
    }
    const text = input;
    setSubmitting(true);
    setError("");
    try {
      const id = conversationId || (await newConversation());
      await api(`/conversations/${id}/messages`, { text });
      setInput("");
      pinned.current = true;
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSubmitting(false);
    }
  };
  const ask = (text: string) => {
    setInput(text);
    composer.current?.focus();
  };
  const timeline = snapshot
    ? [
        ...snapshot.items.map((item) => ({ type: "item", value: item })),
        ...snapshot.experiments.map((value) => ({ type: "experiment", value })),
        ...snapshot.approvals.map((value) => ({ type: "approval", value })),
        ...snapshot.artifacts.map((value) => ({ type: "artifact", value })),
      ].sort((a, b) => a.value.created - b.value.created)
    : [];
  const selectedJob = snapshot?.experiments.find(
    (j) => selected?.type === "experiment" && j.id === selected.id,
  );
  const selectedArtifact = snapshot?.artifacts.find(
    (a) => selected?.type === "artifact" && a.id === selected.id,
  );
  const drag = (event: React.PointerEvent) => {
    const startX = event.clientX,
      width = canvasWidth;
    event.currentTarget.setPointerCapture(event.pointerId);
    const target = event.currentTarget;
    const move = (e: Event) =>
      setCanvasWidth(
        Math.min(
          window.innerWidth - 430,
          Math.max(440, width + startX - (e as PointerEvent).clientX),
        ),
      );
    const stop = () => {
      target.removeEventListener("pointermove", move);
      target.removeEventListener("pointerup", stop);
    };
    target.addEventListener("pointermove", move);
    target.addEventListener("pointerup", stop);
  };
  return (
    <div className={`app ${sidebar ? "" : "sidebar-hidden"}`}>
      {sidebar && (
        <aside className="sidebar">
          <div className="brand">
            <span className="brand-mark">
              <Activity size={23} />
            </span>
            <span>
              observa<span className="brand-studio">STUDIO</span>
            </span>
            <button
              className="icon-button"
              title="Hide sidebar"
              onClick={() => setSidebar(false)}
            >
              <PanelLeftClose size={17} />
            </button>
          </div>
          <button
            className="new-chat"
            onClick={() => newConversation().catch((e) => setError(e.message))}
          >
            <Plus size={18} /> New conversation <span>↗</span>
          </button>
          <label className="search">
            <Search size={16} />
            <input
              placeholder="Search research"
              aria-label="Search research"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            {query && (
              <button
                className="icon-button"
                title="Clear search"
                onClick={() => setQuery("")}
              >
                <X size={13} />
              </button>
            )}
          </label>
          <label className="provider-choice">
            Agent for new conversations
            <select
              aria-label="Agent for new conversations"
              value={newProvider}
              onChange={(e) => setNewProvider(e.target.value)}
            >
              {providers.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.label}
                  {p.installed ? "" : " (not installed)"}
                </option>
              ))}
            </select>
          </label>
          <div className="sidebar-section">
            <span>PROJECTS</span>
            <button
              className="icon-button"
              title="Create project"
              onClick={() => setProjectModal(true)}
            >
              <FolderPlus size={16} />
            </button>
          </div>
          <div className="project-list">
            {projects.map((p) => (
              <button
                key={p.id}
                className={`project ${p.id === projectId ? "selected" : ""}`}
                title={p.path}
                onClick={() => {
                  setProjectId(p.id);
                  setConversationId("");
                }}
              >
                <Folder size={16} />
                <span>{p.name}</span>
                {p.id === projectId && <ChevronDown size={13} />}
              </button>
            ))}
            {!projects.length && (
              <button className="project" onClick={() => setProjectModal(true)}>
                <FolderPlus size={16} /> Create your first project
              </button>
            )}
          </div>
          <div className="sidebar-section">
            <span>{query ? "SEARCH RESULTS" : "CONVERSATIONS"}</span>
            <History size={14} />
          </div>
          <div className="conversation-list">
            {[...conversations]
              .reverse()
              .filter((c) => query || c.project === projectId)
              .map((c) => (
                <button
                  key={c.id}
                  className={conversationId === c.id ? "selected" : ""}
                  onClick={() => {
                    setSettingsSection("");
                    setConversationId(c.id);
                    setProjectId(c.project);
                  }}
                >
                  <MessageSquare size={15} />
                  <span>{c.title}</span>
                  {active(c.status) && <span className="live-dot" />}
                </button>
              ))}
            {!conversations.filter((c) => query || c.project === projectId)
              .length && (
              <p className="sidebar-empty">
                {query
                  ? "No matching conversations."
                  : "Your research starts here."}
              </p>
            )}
          </div>
          <div className="sidebar-footer">
            <span className="local-indicator" />
            <div>
              <b>Local workspace</b>
              <span>Research stays on this machine</span>
            </div>
            <CircleHelp size={16} />
          </div>
        </aside>
      )}
      <div className="workspace">
        <header className="topbar">
          {!sidebar && (
            <button
              className="icon-button"
              title="Show sidebar"
              onClick={() => setSidebar(true)}
            >
              <PanelLeftOpen size={18} />
            </button>
          )}
          <span className="breadcrumb">
            <Folder size={15} /> {project?.name || "Your workspace"}{" "}
            <ChevronRight size={13} />{" "}
            <b>{snapshot?.conversation.title || "New research"}</b>
          </span>
          <div className="topbar-right">
            {snapshot && (
              <button
                className="stop-agent"
                type="button"
                onClick={stop}
                disabled={!stoppable || stopping}
                aria-label="Stop agent"
                title={`Stop ${providerLabel} and active backtests`}
              >
                {stopping ? (
                  <LoaderCircle className="spin" size={14} />
                ) : (
                  <Square size={13} />
                )}
                {stopping ? "Stopping…" : "Stop agent"}
              </button>
            )}
            <span className="provider">
              <span className={`provider-dot ${!connected ? "offline" : ""}`} />
              {providerLabel}{" "}
              <span className="provider-mode">
                {connected ? "Local session" : "Disconnected"}
              </span>
            </span>
            {snapshot?.experiments.some((j) => j.status === "completed") && (
              <button
                className="icon-button"
                title="Open latest research result"
                onClick={() =>
                  setSelected({
                    type: "experiment",
                    id: snapshot.experiments
                      .filter((j) => j.status === "completed")
                      .at(-1)!.id,
                  })
                }
              >
                <BarChart3 size={18} />
              </button>
            )}
          </div>
        </header>
        {(error || snapshot?.conversation.error) && (
          <div className="global-error" role="alert">
            <span>{error || snapshot?.conversation.error}</span>
            <button
              className="icon-button"
              title="Dismiss error"
              onClick={() => {
                setError("");
                setSnapshot((s) =>
                  s
                    ? { ...s, conversation: { ...s.conversation, error: null } }
                    : s,
                );
              }}
            >
              <X size={16} />
            </button>
          </div>
        )}
        {notice && (
          <div className="notice">
            {notice}
            <button
              className="icon-button"
              title="Dismiss notice"
              onClick={() => setNotice("")}
            >
              <X size={14} />
            </button>
          </div>
        )}
        {!connected && (
          <div className="notice">
            Connection lost. Agent status cannot be confirmed. Reconnecting… If
            Studio has stopped, reopen its launch link. To stop it from the
            terminal, press Ctrl+C.
          </div>
        )}
        <div className={`workspace-body ${selected ? "with-canvas" : ""}`}>
          <main className="chat">
            <div
              className="chat-scroll"
              ref={scroller}
              onScroll={() => {
                const el = scroller.current!;
                pinned.current =
                  el.scrollHeight - el.scrollTop - el.clientHeight < 100;
              }}
            >
              {!timeline.length ? (
                <div className="welcome">
                  <div className="welcome-mark">
                    <Activity size={35} strokeWidth={1.5} />
                  </div>
                  <span className="eyebrow">FROM IDEA TO EVIDENCE</span>
                  <h1>
                    What would you like
                    <br />
                    to investigate?
                  </h1>
                  <p>
                    A workspace for thoughtful strategy research.
                    <br />
                    Build with your agent. Test with Observa. Follow the
                    evidence.
                  </p>
                  <div className="starter-grid">
                    <button
                      onClick={() =>
                        ask(
                          "Create a simple moving-average strategy using the bundled sample dataset. Explain your assumptions, then prepare a backtest for my approval. Use interval 15m and report canonical results.",
                        )
                      }
                    >
                      <BarChart3 size={20} />
                      <strong>Test a strategy</strong>
                      <span>Turn an idea into a reproducible backtest</span>
                      <ArrowUpRight size={15} />
                    </button>
                    <button
                      onClick={() =>
                        ask(
                          "Help me plan a strategy research experiment. Start by checking the Observa contract and asking about the hypothesis, dataset, and execution assumptions.",
                        )
                      }
                    >
                      <Sparkles size={20} />
                      <strong>Explore a hypothesis</strong>
                      <span>Find a clear question worth testing</span>
                      <ArrowUpRight size={15} />
                    </button>
                  </div>
                  {!project && (
                    <button
                      className="text-button"
                      onClick={() => setProjectModal(true)}
                    >
                      <FolderPlus size={15} /> Create a project to get started
                    </button>
                  )}
                </div>
              ) : (
                <div className="messages">
                  {timeline.map(({ type, value }) => (
                    <div key={value.id} className="timeline-entry">
                      {type === "item" &&
                        (value.type === "user" ? (
                          <div className="user-message">{value.text}</div>
                        ) : value.type === "agentMessage" ? (
                          <div className="agent-message">
                            <div className="agent-label">
                              <span className="mini-brand">
                                <Activity size={15} />
                              </span>
                              {providerLabel}
                            </div>
                            <Markdown text={value.text || ""} />
                          </div>
                        ) : (
                          <Tool item={value} connected={connected} />
                        ))}
                      {type === "approval" && (
                        <Approval
                          providerLabel={providerLabel}
                          approval={value}
                          item={snapshot?.items.find(
                            (i) => i.provider_id === value.params.itemId,
                          )}
                          act={act}
                        />
                      )}
                      {type === "experiment" && (
                        <Experiment
                          job={value}
                          act={act}
                          open={() =>
                            setSelected({ type: "experiment", id: value.id })
                          }
                        />
                      )}
                      {type === "artifact" && (
                        <button
                          className="artifact-card"
                          onClick={() =>
                            setSelected({ type: "artifact", id: value.id })
                          }
                        >
                          <BarChart3 size={22} />
                          <span>
                            <b>{value.title}</b>
                            <small>Agent-generated {value.kind}</small>
                          </span>
                          <ArrowUpRight size={18} />
                        </button>
                      )}
                    </div>
                  ))}
                  {running && connected && (
                    <div className="agent-working">
                      <span className="breathing-dot" />
                      {stopping || snapshot?.conversation.status === "stopping"
                        ? `Stopping ${providerLabel}…`
                        : snapshot?.conversation.status === "connecting"
                          ? `Connecting to ${providerLabel}…`
                          : `${providerLabel} is working`}
                      {snapshot?.conversation.model && (
                        <small>{snapshot.conversation.model}</small>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
            <div className="composer-zone">
              <form className="composer" onSubmit={send}>
                {input.startsWith("/") && (
                  <div className="slash-menu" aria-label="Studio commands">
                    {commands
                      .filter(
                        ([command]) =>
                          !["model", "mode", "permissions"].includes(command) ||
                          supports(command),
                      )
                      .filter(([command]) =>
                        command.startsWith(input.slice(1).toLowerCase()),
                      )
                      .map(([command, description]) => (
                        <button
                          type="button"
                          key={command}
                          onClick={() =>
                            runCommand(command).catch((e) =>
                              setError(e.message),
                            )
                          }
                        >
                          <b>/{command}</b>
                          <span>{description}</span>
                        </button>
                      ))}
                  </div>
                )}
                <textarea
                  ref={composer}
                  placeholder={`Ask ${providerLabel}, or type / for settings…`}
                  aria-label={`Message ${providerLabel}`}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (
                      e.key === "Enter" &&
                      !e.shiftKey &&
                      !e.nativeEvent.isComposing
                    ) {
                      e.preventDefault();
                      send();
                    }
                  }}
                  rows={2}
                  disabled={!ready}
                />
                <div className="composer-toolbar">
                  <button
                    type="button"
                    className="composer-setting"
                    onClick={() => openSettings("permissions")}
                    disabled={
                      stoppable || !connected || !supports("permissions")
                    }
                    title="Permissions (/permissions)"
                  >
                    <ShieldCheck size={14} />{" "}
                    {
                      permissionLabels[
                        snapshot?.conversation.settings?.permissions ||
                          "cautious"
                      ]
                    }
                  </button>
                  <div>
                    <button
                      type="button"
                      className="composer-setting"
                      title="Mode (/mode)"
                      disabled={stoppable || !connected || !supports("mode")}
                      onClick={() => openSettings("mode")}
                    >
                      {snapshot?.conversation.settings?.mode === "plan"
                        ? "Plan"
                        : "Default"}
                    </button>
                    <button
                      type="button"
                      className="composer-setting"
                      title="Model and reasoning (/model)"
                      disabled={stoppable || !connected || !supports("model")}
                      onClick={() => openSettings("model")}
                    >
                      {snapshot?.conversation.settings?.model ||
                        snapshot?.conversation.model ||
                        providerLabel}
                    </button>
                    {stoppable ? (
                      <button
                        type="button"
                        className="send-button stop"
                        title={`Stop ${providerLabel} and active backtests`}
                        aria-label="Stop research"
                        disabled={stopping}
                        onClick={stop}
                      >
                        <Square size={15} fill="currentColor" />
                      </button>
                    ) : (
                      <button
                        className="send-button"
                        title="Send message"
                        disabled={
                          !input.trim() ||
                          submitting ||
                          !ready ||
                          !connected ||
                          stopping
                        }
                      >
                        {submitting ? (
                          <LoaderCircle size={17} className="spin" />
                        ) : (
                          <ArrowUp size={19} />
                        )}
                      </button>
                    )}
                  </div>
                </div>
              </form>
              <p className="composer-footnote">
                Local files & history · {providerLabel} uses your configured
                account and may send context to its model service
              </p>
            </div>
          </main>
          {selected && (
            <>
              <div
                className="canvas-divider"
                role="separator"
                aria-label="Resize research canvas"
                aria-orientation="vertical"
                aria-valuemin={440}
                aria-valuemax={Math.max(440, window.innerWidth - 430)}
                aria-valuenow={canvasWidth}
                tabIndex={0}
                onKeyDown={(event) => {
                  if (["ArrowLeft", "ArrowRight"].includes(event.key)) {
                    event.preventDefault();
                    setCanvasWidth((width) =>
                      Math.min(
                        window.innerWidth - 430,
                        Math.max(
                          440,
                          width + (event.key === "ArrowLeft" ? 30 : -30),
                        ),
                      ),
                    );
                  }
                }}
                onPointerDown={drag}
              />
              <div className="canvas-slot" style={{ width: canvasWidth }}>
                {selectedJob && (
                  <Research
                    key={selectedJob.id}
                    job={selectedJob}
                    close={() => setSelected(null)}
                    ask={ask}
                  />
                )}
                {selectedArtifact && (
                  <Artifact
                    artifact={selectedArtifact}
                    close={() => setSelected(null)}
                  />
                )}
              </div>
            </>
          )}
        </div>
      </div>
      {settingsSection && snapshot && (
        <AgentSettings
          provider={selectedProvider}
          key={snapshot.conversation.id}
          conversation={snapshot.conversation}
          section={settingsSection}
          close={() => setSettingsSection("")}
          saved={(conversation) => {
            setSnapshot((s) =>
              s && s.conversation.id === conversation.id
                ? { ...s, conversation }
                : s,
            );
            setConversations((list) => upsert(list, conversation));
            setSettingsSection("");
          }}
        />
      )}
      {projectModal && (
        <div
          className="modal-backdrop"
          onClick={(e) => {
            if (e.target === e.currentTarget) setProjectModal(false);
          }}
        >
          <form
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="project-title"
            onSubmit={createProject}
          >
            <div className="section-heading">
              <h2 id="project-title">Create a research project</h2>
              <button
                type="button"
                className="icon-button"
                title="Close dialog"
                onClick={() => setProjectModal(false)}
              >
                <X size={18} />
              </button>
            </div>
            <p>
              Keep related conversations, strategies and experiments together.
            </p>
            <label>
              Project name
              <input
                autoFocus
                required
                maxLength={120}
                placeholder="e.g. FX momentum research"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </label>
            <label>
              Existing project directory{" "}
              <span className="muted">(optional)</span>
              <input
                placeholder="/home/you/research/my-strategy"
                value={path}
                onChange={(e) => setPath(e.target.value)}
              />
            </label>
            <p className="note">
              <Folder size={15} /> Leave empty to create a dedicated folder.
              Your chosen agent can read and edit files in the selected project;
              command permissions appear in chat.
            </p>
            <button className="primary" disabled={submitting || !name.trim()}>
              {submitting ? "Creating…" : "Create project"}
              <ChevronRight size={16} />
            </button>
          </form>
        </div>
      )}
    </div>
  );
}
