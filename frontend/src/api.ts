const TOKEN_KEY = "opschest_token";
const USER_KEY = "opschest_user";

export type User = { username: string; full_name: string; role: "manager" | "staff" };

function store(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

export function getToken(): string | null {
  try {
    return store()?.getItem(TOKEN_KEY) ?? null;
  } catch {
    return null;
  }
}

export function getUser(): User | null {
  try {
    const raw = store()?.getItem(USER_KEY);
    return raw ? (JSON.parse(raw) as User) : null;
  } catch {
    return null;
  }
}

export function saveSession(token: string, user: User) {
  try {
    store()?.setItem(TOKEN_KEY, token);
    store()?.setItem(USER_KEY, JSON.stringify(user));
  } catch {
    /* che do rieng tu: van dung duoc trong phien */
  }
  memToken = token;
}

export function clearSession() {
  try {
    store()?.removeItem(TOKEN_KEY);
    store()?.removeItem(USER_KEY);
  } catch {
    /* bo qua */
  }
  memToken = null;
}

let memToken: string | null = null;

function authHeader(): Record<string, string> {
  const t = getToken() ?? memToken;
  return t ? { Authorization: `Bearer ${t}` } : {};
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function errorFrom(r: Response): Promise<ApiError> {
  let msg = `${r.status} ${r.statusText}`;
  try {
    const j = await r.json();
    if (typeof j.detail === "string") msg = j.detail;
    else if (Array.isArray(j.detail)) msg = j.detail.map((d: { msg: string }) => d.msg).join("; ");
  } catch {
    /* khong phai JSON */
  }
  if (r.status === 401 && !location.pathname.startsWith("/login")) {
    clearSession();
    location.href = "/login";
  }
  return new ApiError(r.status, msg);
}

export async function api<T = unknown>(path: string, opts: { method?: string; body?: unknown } = {}): Promise<T> {
  const r = await fetch(`/api${path}`, {
    method: opts.method ?? "GET",
    headers: { "Content-Type": "application/json", ...authHeader() },
    body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
  });
  if (!r.ok) throw await errorFrom(r);
  return (await r.json()) as T;
}

export async function openPdf(poId: number) {
  const r = await fetch(`/api/purchase-orders/${poId}/pdf`, { headers: authHeader() });
  if (!r.ok) throw await errorFrom(r);
  const url = URL.createObjectURL(await r.blob());
  window.open(url, "_blank", "noopener");
}

export type ChatEvent =
  | { type: "token"; text: string }
  | { type: "tool_call"; id: string; name: string; args: Record<string, unknown>; kind: string | null }
  | { type: "tool_result"; id: string; name: string; ok: boolean; error: string | null }
  | { type: "chart"; spec: ChartSpec }
  | { type: "proposal"; proposal: Proposal }
  | ({ type: "widget" } & WidgetSpec)
  | { type: "provider"; model: string; fallback: boolean }
  | { type: "guard"; ungrounded_numbers: string[]; false_exec: boolean }
  | { type: "error"; message: string }
  | { type: "done"; metrics?: TurnMetrics };

export type TurnMetrics = {
  seconds: number;
  llm_seconds: number;
  rounds: number;
  prompt_tokens: number;
  completion_tokens: number;
  usage_reported: boolean;
};

export async function streamChat(sessionId: number, text: string, onEvent: (e: ChatEvent) => void) {
  const r = await fetch(`/api/chat/sessions/${sessionId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeader() },
    body: JSON.stringify({ text }),
  });
  if (!r.ok || !r.body) throw await errorFrom(r);
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const chunk = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      const line = chunk.split("\n").find((l) => l.startsWith("data: "));
      if (line) onEvent(JSON.parse(line.slice(6)) as ChatEvent);
    }
  }
}

// ---------- Kieu du lieu dung chung ----------
export type WidgetFmt = "text" | "num" | "money" | "pct" | "date" | "days" | "badge" | "ptype";
export type WidgetSpec =
  | {
      kind: "table";
      title: string;
      columns: { key: string; label: string; fmt: WidgetFmt }[];
      rows: Record<string, string | number | null>[];
      more: number;
      note: string | null;
      empty: string;
    }
  | {
      kind: "kpis";
      title: string;
      items: { label: string; value: number | null; fmt: WidgetFmt; prev: number | null; lower_is_better: boolean }[];
      note: string | null;
    }
  | {
      kind: "form";
      form: "receive_po";
      title: string;
      meta: { po_id: number; code: string; supplier: string; expected_date: string };
      lines: { line_id: number; sku: string; name: string; qty: number; received_qty: number | null; default_expiry: string }[];
      submit: { method: string; path: string };
      note: string | null;
    };

export type ChartSpec = {
  metric: string;
  type: "bar" | "line" | "hbar" | "matrix";
  title: string;
  period: string;
  x_key: string;
  unit: string;
  stacked?: boolean;
  series: { key: string; label: string }[];
  data: Record<string, number | string>[];
  row_count: number;
};

export type Proposal = {
  id: number;
  type: "PURCHASE_ORDER" | "MARKDOWN" | "RETURN" | "DISPOSE" | "DELIST";
  status: "PENDING" | "APPROVED" | "EXECUTED" | "FAILED" | "REJECTED" | "EXPIRED";
  title: string;
  rationale: string;
  evidence: Record<string, unknown>;
  payload: Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
  original_payload: Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
  sm_edits: { by: string; at: string; changes: { field: string; from: unknown; to: unknown }[] }[];
  est_value: number | null;
  created_by: string;
  created_at: string | null;
  expires_at: string | null;
  decided_by: string | null;
  decided_at: string | null;
  decision_note: string | null;
  executed_at: string | null;
  execution_result: Record<string, unknown> | null;
};
