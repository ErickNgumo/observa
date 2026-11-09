import { useEffect, useRef, useState } from "react";
import { LoaderCircle, X } from "lucide-react";
import { api, type RecordData } from "./api";

export const commands = [
  ["model", "Choose model and reasoning effort"],
  ["mode", "Choose an available agent mode"],
  ["permissions", "Choose how your agent approves actions"],
  ["status", "Show this conversation's agent settings"],
  ["stop", "Stop the agent and active backtests"],
  ["new", "Start a new conversation"],
  ["help", "Show available Studio commands"],
];
export const permissionLabels: Record<string, string> = {
  cautious: "Ask before commands",
  default: "Ask when needed",
  automatic: "Approve for me",
  "read-only": "Read only",
  sandboxed: "Automatic within sandbox",
  "full-access": "Full access",
};

export default function AgentSettings({
  provider,
  conversation,
  section,
  close,
  saved,
}: {
  provider: any;
  conversation: RecordData;
  section: string;
  close: () => void;
  saved: (conversation: RecordData) => void;
}) {
  const label = provider?.label || "Agent";
  const [options, setOptions] = useState<any>(null);
  const [value, setValue] = useState<any>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [probe, setProbe] = useState<any>(null);
  const [checking, setChecking] = useState(false);
  const form = useRef<HTMLFormElement>(null);
  useEffect(() => {
    let disposed = false;
    api(`/conversations/${conversation.id}/options`)
      .then((o) => {
        if (disposed) return;
        const s = conversation.settings || {};
        const model =
          o.models.find(
            (m: any) => m.model === (s.model || conversation.model),
          ) ||
          o.models.find((m: any) => m.isDefault) ||
          o.models[0];
        if (!model) throw new Error(`${label} returned no available models.`);
        setOptions(o);
        setValue({
          model: model.model,
          effort: s.effort || model.defaultReasoningEffort,
          mode: s.mode || "default",
          permissions: s.permissions || "cautious",
        });
      })
      .catch((e) => {
        if (!disposed) setError(e.message);
      });
    return () => {
      disposed = true;
    };
  }, [conversation.id]);
  useEffect(() => {
    if (options)
      form.current
        ?.querySelector<HTMLSelectElement>(`[name="${section}"]`)
        ?.focus();
  }, [options, section]);
  const model = options?.models.find((m: any) => m.model === value?.model);
  const permission = options?.permissions.find(
    (p: any) => p.id === value?.permissions,
  );
  return (
    <div
      className="modal-backdrop"
      onClick={(e) => {
        if (e.target === e.currentTarget && !busy) close();
      }}
    >
      <form
        ref={form}
        className="modal agent-settings"
        role="dialog"
        aria-modal="true"
        aria-labelledby="settings-title"
        onKeyDown={(e) => {
          if (e.key === "Escape" && !busy) close();
        }}
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setError("");
          try {
            saved(
              await api(`/conversations/${conversation.id}/settings`, {
                ...value,
                confirm_full_access: confirmed,
              }),
            );
          } catch (e: any) {
            setError(e.message);
          } finally {
            setBusy(false);
          }
        }}
      >
        <div className="section-heading">
          <h2 id="settings-title">{label} settings</h2>
          <button
            className="icon-button"
            type="button"
            title="Close settings"
            disabled={busy}
            onClick={close}
          >
            <X size={18} />
          </button>
        </div>
        <p>Saved for this conversation. Changes apply to the next message.</p>
        <button
          type="button"
          disabled={checking}
          onClick={async () => {
            setChecking(true);
            try {
              setProbe(
                await api(`/conversations/${conversation.id}/probe`, {}),
              );
            } catch (e: any) {
              setProbe({ status: "unknown", message: e.message });
            } finally {
              setChecking(false);
            }
          }}
        >
          {checking ? "Checking connection…" : "Check agent connection"}
        </button>
        {probe && <p role="status">{probe.message}</p>}
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        {!options && !error && (
          <p>
            <LoaderCircle size={16} className="spin" /> Reading your installed
            {label}…
          </p>
        )}
        {options && value && (
          <>
            <label>
              Model
              <select
                aria-label="Model"
                name="model"
                value={value.model}
                onChange={(e) => {
                  const m = options.models.find(
                    (m: any) => m.model === e.target.value,
                  );
                  setValue({
                    ...value,
                    model: m.model,
                    effort: m.defaultReasoningEffort,
                  });
                }}
              >
                {options.models.map((m: any) => (
                  <option key={m.model} value={m.model}>
                    {m.displayName}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Reasoning effort
              <select
                aria-label="Reasoning effort"
                value={value.effort}
                onChange={(e) => setValue({ ...value, effort: e.target.value })}
              >
                {model?.supportedReasoningEfforts.map((r: any) => (
                  <option key={r.reasoningEffort} value={r.reasoningEffort}>
                    {r.reasoningEffort}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Mode
              <select
                aria-label="Mode"
                name="mode"
                value={value.mode}
                onChange={(e) => setValue({ ...value, mode: e.target.value })}
              >
                {options.modes.map((m: any) => (
                  <option key={m.mode} value={m.mode}>
                    {m.name}
                  </option>
                ))}
              </select>
            </label>
            <p className="note">
              {value.mode === "plan"
                ? `Plan with ${label} before implementation. Switch to an execution mode when ready.`
                : `${label} uses its native tools and permissions for research.`}
            </p>
            <label>
              Permissions
              <select
                aria-label="Permissions"
                name="permissions"
                value={value.permissions}
                onChange={(e) => {
                  setValue({ ...value, permissions: e.target.value });
                  setConfirmed(false);
                }}
              >
                {options.permissions.map((p: any) => (
                  <option
                    key={p.id}
                    value={p.id}
                    disabled={Boolean(p.disabled_reason)}
                  >
                    {p.label}
                    {p.disabled_reason ? " (restricted)" : ""}
                  </option>
                ))}
              </select>
            </label>
            <p className="note">
              {permission?.description} {permission?.disabled_reason}
            </p>
            {value.permissions === "full-access" && (
              <label className="access-confirm">
                <input
                  type="checkbox"
                  checked={confirmed}
                  onChange={(e) => setConfirmed(e.target.checked)}
                />
                I allow {label} unrestricted filesystem and network access
                without command approvals for this conversation.
              </label>
            )}
            <p className="note">
              Observa backtests prepared through Studio still require your
              separate approval of the code and data snapshot.
            </p>
            <button
              className="primary"
              disabled={
                busy ||
                Boolean(permission?.disabled_reason) ||
                (value.permissions === "full-access" && !confirmed)
              }
            >
              {busy ? "Saving…" : "Save settings"}
            </button>
          </>
        )}
      </form>
    </div>
  );
}
