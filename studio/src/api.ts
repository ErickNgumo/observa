export async function api(path: string, body?: unknown) {
  const response = await fetch("/api" + path, {
    method: body === undefined ? "GET" : "POST",
    headers: { "Content-Type": "application/json", "X-Observa-Request": "1" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const value = await response.json();
  if (!response.ok)
    throw new Error(
      typeof value.detail === "string"
        ? value.detail
        : JSON.stringify(value.detail),
    );
  return value;
}

export async function authenticate() {
  const token = new URLSearchParams(location.hash.slice(1)).get("token");
  if (token) {
    const response = await fetch("/api/auth", {
      method: "POST",
      headers: { Authorization: "Bearer " + token },
    });
    history.replaceState(null, "", location.pathname);
    if (!response.ok)
      throw new Error(
        "The launch link has expired. Open the link printed by observa studio.",
      );
  }
}

export type RecordData = {
  id: string;
  created: number;
  updated: number;
  [key: string]: any;
};
export type Snapshot = {
  conversation: RecordData;
  provider?: {
    id: string;
    label: string;
    capabilities: string[];
    installed: boolean;
  };
  items: RecordData[];
  experiments: RecordData[];
  approvals: RecordData[];
  artifacts: RecordData[];
  cursor: number;
};

export function canStop(snapshot: Snapshot | null): boolean {
  if (!snapshot) return false;
  const conversation = snapshot.conversation;
  return (
    ["connecting", "running", "stopping"].includes(conversation.status) ||
    Boolean(conversation.turn_id) ||
    snapshot.items.some((item) => item.status === "running") ||
    snapshot.approvals.some((approval) => approval.status === "pending") ||
    snapshot.experiments.some((job) =>
      ["awaiting_approval", "queued", "running"].includes(job.status),
    )
  );
}

export function upsert(list: RecordData[], item: RecordData) {
  return list.some((i) => i.id === item.id)
    ? list.map((i) => (i.id === item.id ? item : i))
    : [...list, item];
}

export function number(value: unknown, digits = 2): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  const magnitude = Math.abs(value);
  if (magnitude > 0 && magnitude < 0.000001) return value.toExponential(3);
  return value.toLocaleString(undefined, {
    maximumFractionDigits:
      magnitude > 0 && magnitude < 0.01 ? Math.max(digits, 6) : digits,
  });
}
