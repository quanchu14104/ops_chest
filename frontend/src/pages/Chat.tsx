import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { api, runCommand, streamChat, type ChartSpec, type ChatEvent, type Proposal, type TurnMetrics, type WidgetSpec } from "../api";
import ChartView from "../components/ChartView";
import ProposalCard, { ASK_EVENT, type AskDetail } from "../components/ProposalCard";
import Briefing from "../components/Briefing";
import Widget from "../components/Widgets";
import { TaskMenu, openTask } from "../components/Tasks";

type ToolCall = { id: string; name: string; ok?: boolean; error?: string | null };
type Block =
  | { kind: "text"; text: string }
  | { kind: "tools"; calls: ToolCall[] }
  | { kind: "chart"; spec: ChartSpec }
  | { kind: "proposal"; proposal: Proposal }
  | { kind: "widget"; spec: WidgetSpec }
  | { kind: "guard"; numbers: string[]; falseExec: boolean };
type Turn = { role: "user" | "assistant"; blocks: Block[]; model?: string; fallback?: boolean; metrics?: TurnMetrics };

type ServerMsg = {
  role: string;
  content: string | null;
  name: string | null;
  tool_calls: { id: string; name: string }[];
  tool_call_id: string | null;
  ui_events: (
    | { type: "chart"; spec: ChartSpec }
    | { type: "proposal"; proposal: Proposal }
    | ({ type: "widget" } & WidgetSpec)
    | { type: "guard"; ungrounded_numbers: string[]; false_exec: boolean }
  )[];
};

const TOOL_LABEL: Record<string, string> = {
  get_inventory_summary: "Xem tổng quan tồn kho",
  search_products: "Tìm sản phẩm",
  get_product_detail: "Xem chi tiết SKU",
  get_expiring_lots: "Quét hàng cận date",
  get_stock_flow: "Lấy số liệu nhập/xuất",
  get_sales_summary: "Lấy doanh số",
  get_cost_report: "Lập báo cáo chi phí",
  get_abc_xyz: "Phân nhóm hàng theo mức bán",
  get_delist_candidates: "Tìm ứng viên ngừng nhập",
  list_suppliers: "Xem nhà cung cấp",
  preview_reorder: "Tính thử số lượng đặt",
  list_proposals: "Xem đề xuất",
  get_kpi_dashboard: "Xem KPI",
  open_receive_form: "Mở form nhận hàng",
  open_approval_inbox: "Mở thẻ duyệt",
  open_expiring_panel: "Mở thẻ hàng cận date",
  open_purchase_orders: "Mở đơn chờ giao",
  open_supplier_returns: "Mở phiếu trả NCC",
  open_stock_count_form: "Mở phiếu kiểm kê",
  open_date_check_form: "Mở phiếu kiểm date",
  open_pull_form: "Mở phiếu rút kệ",
  list_supplier_returns: "Xem phiếu trả NCC",
  get_supplier_scorecard: "Xem điểm NCC",
  propose_write_off: "Tạo đề xuất báo hủy",
  propose_demand_hypothesis: "Ghi giả thuyết nhu cầu",
  list_demand_hypotheses: "Xem giả thuyết nhu cầu",
  get_order_edit_patterns: "Xem thói quen sửa đơn",
  propose_order_adjustment: "Đề xuất hệ số đặt hàng",
  build_chart: "Vẽ biểu đồ",
  propose_purchase_order: "Tạo đề xuất đặt hàng",
  propose_markdown: "Tạo đề xuất giảm giá",
  propose_supplier_return: "Tạo đề xuất trả NCC",
  propose_dispose_expired: "Tạo đề xuất ghi hủy",
  propose_delist: "Tạo đề xuất ngừng nhập",
  revise_proposal: "Sửa đề xuất (tạo bản mới)",
};

// Menu Công việc và popup từng việc: components/Tasks.tsx. Sự kiện dưới đây vẫn cho phép chèn thẻ vào luồng chat.
export const COMMAND_EVENT = "opschest:command";

// Bo truong `type` cua su kien SSE, phan con lai la WidgetSpec
function widgetSpec(e: { type: "widget" } & WidgetSpec): WidgetSpec {
  const { type: _type, ...spec } = e;
  return spec as WidgetSpec;
}

function fromServer(msgs: ServerMsg[]): Turn[] {
  const turns: Turn[] = [];
  let cur: Turn | null = null;
  const toolIndex: Record<string, ToolCall> = {};
  for (const m of msgs) {
    if (m.role === "user") {
      turns.push({ role: "user", blocks: [{ kind: "text", text: m.content ?? "" }] });
      cur = null;
      continue;
    }
    if (!cur) {
      cur = { role: "assistant", blocks: [] };
      turns.push(cur);
    }
    if (m.role === "assistant") {
      // Lệnh nhanh (name = "command") không qua LLM: không hiện tên model hay chip "đang tra dữ liệu"
      const isCommand = m.name === "command";
      if (m.name && !isCommand) cur.model = m.name;
      if (m.content) cur.blocks.push({ kind: "text", text: m.content });
      if (m.tool_calls.length && !isCommand) {
        const calls = m.tool_calls.map((t) => (toolIndex[t.id] = { id: t.id, name: t.name }));
        cur.blocks.push({ kind: "tools", calls });
      }
      for (const u of m.ui_events) {
        if (u.type === "guard") cur.blocks.push({ kind: "guard", numbers: u.ungrounded_numbers, falseExec: u.false_exec });
      }
    } else if (m.role === "tool") {
      const tc = m.tool_call_id ? toolIndex[m.tool_call_id] : undefined;
      if (tc) tc.ok = true;
      for (const u of m.ui_events) {
        if (u.type === "chart") cur.blocks.push({ kind: "chart", spec: u.spec });
        else if (u.type === "proposal") cur.blocks.push({ kind: "proposal", proposal: u.proposal });
        else if (u.type === "widget") cur.blocks.push({ kind: "widget", spec: widgetSpec(u) });
      }
    }
  }
  return turns;
}

function apply(turn: Turn, e: ChatEvent): Turn {
  const blocks = [...turn.blocks];
  const last = blocks[blocks.length - 1];
  switch (e.type) {
    case "token":
      if (last?.kind === "text") blocks[blocks.length - 1] = { kind: "text", text: last.text + e.text };
      else blocks.push({ kind: "text", text: e.text });
      break;
    case "tool_call":
      if (last?.kind === "tools") blocks[blocks.length - 1] = { kind: "tools", calls: [...last.calls, { id: e.id, name: e.name }] };
      else blocks.push({ kind: "tools", calls: [{ id: e.id, name: e.name }] });
      break;
    case "tool_result":
      for (let i = blocks.length - 1; i >= 0; i--) {
        const b = blocks[i];
        if (b.kind === "tools" && b.calls.some((c) => c.id === e.id)) {
          blocks[i] = { kind: "tools", calls: b.calls.map((c) => (c.id === e.id ? { ...c, ok: e.ok, error: e.error } : c)) };
          break;
        }
      }
      break;
    case "chart":
      blocks.push({ kind: "chart", spec: e.spec });
      break;
    case "proposal":
      blocks.push({ kind: "proposal", proposal: e.proposal });
      break;
    case "widget":
      blocks.push({ kind: "widget", spec: widgetSpec(e) });
      break;
    case "guard":
      blocks.push({ kind: "guard", numbers: e.ungrounded_numbers, falseExec: e.false_exec });
      break;
    case "done":
      return { ...turn, blocks, metrics: e.metrics };
    case "provider":
      return { ...turn, blocks, model: e.model, fallback: turn.fallback || e.fallback };
    case "error":
      blocks.push({ kind: "text", text: `⚠️ ${e.message}` });
      break;
  }
  return { ...turn, blocks };
}

// Markdown toi gian an toan (khong dung innerHTML): **dam**, danh sach "- ", tieu de "#"
function Inline({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
  return (
    <>
      {parts.map((p, i) =>
        p.startsWith("**") && p.endsWith("**") ? <b key={i}>{p.slice(2, -2)}</b> : p.startsWith("`") && p.endsWith("`") ? <code key={i}>{p.slice(1, -1)}</code> : <Fragment key={i}>{p}</Fragment>,
      )}
    </>
  );
}

function Markdown({ text }: { text: string }) {
  const lines = text.split("\n");
  const out: JSX.Element[] = [];
  let list: string[] = [];
  const flush = () => {
    if (list.length) {
      out.push(
        <ul key={`u${out.length}`}>
          {list.map((l, i) => (
            <li key={i}>
              <Inline text={l} />
            </li>
          ))}
        </ul>,
      );
      list = [];
    }
  };
  for (const raw of lines) {
    const l = raw.trimEnd();
    const m = l.match(/^\s*(?:[-*•]|\d+\.)\s+(.*)$/);
    if (m) {
      list.push(m[1]);
      continue;
    }
    flush();
    if (!l.trim()) continue;
    const h = l.match(/^#{1,4}\s+(.*)$/);
    out.push(
      h ? <h3 key={out.length}><Inline text={h[1]} /></h3> : <p key={out.length}><Inline text={l} /></p>,
    );
  }
  flush();
  return <>{out}</>;
}

function AssistantTurn({ turn, streaming }: { turn: Turn; streaming: boolean }) {
  return (
    <div className="msg assistant">
      {turn.blocks.map((b, i) => {
        if (b.kind === "text") return b.text.trim() ? <div key={i} className="bubble" style={{ marginBottom: 8 }}><Markdown text={b.text} /></div> : null;
        if (b.kind === "tools")
          return (
            <div key={i} style={{ marginBottom: 6 }}>
              {b.calls.map((c) => (
                <span key={c.id} className={`toolchip ${c.ok === false ? "err" : ""}`} title={c.error ?? c.name}>
                  {c.ok === undefined ? "⋯" : c.ok ? "✓" : "✕"} {TOOL_LABEL[c.name] ?? c.name}
                </span>
              ))}
            </div>
          );
        if (b.kind === "widget") return <div key={i} style={{ marginBottom: 8 }}><Widget spec={b.spec} /></div>;
        if (b.kind === "chart") return <div key={i} style={{ marginBottom: 8 }}><ChartView spec={b.spec} /></div>;
        if (b.kind === "guard")
          return (
            <div key={i} className="alert warn" style={{ marginBottom: 8 }}>
              ⚠ Cần kiểm tra lại câu trả lời trên:
              {b.numbers.length > 0 && <> các số <b>{b.numbers.join(", ")}</b> không có trong dữ liệu mà hệ thống tra cứu được.</>}
              {b.falseExec && <> câu trả lời có vẻ nói như đã thực hiện hành động, nhưng Ops Chest chỉ tạo đề xuất chờ duyệt.</>}
            </div>
          );
        return <div key={i} style={{ marginBottom: 8 }}><ProposalCard p={b.proposal} compact /></div>;
      })}
      {streaming && <span className="typing-dots" role="status" aria-label="Ops Chest đang trả lời"><i /><i /><i /></span>}
      {!streaming && turn.model && (
        <div className="small muted" title="Model đã trả lời lượt này">
          {turn.model}
          {turn.metrics && (
            <span title="Tổng thời gian · số vòng gọi LLM · token vào/ra">
              {" · "}{turn.metrics.seconds.toFixed(1)}s · {turn.metrics.rounds} vòng
              {turn.metrics.usage_reported && <> · {turn.metrics.prompt_tokens}↑ {turn.metrics.completion_tokens}↓ token</>}
            </span>
          )}
          {turn.fallback && <span className="badge" style={{ marginLeft: 6 }}>LLM phụ: LLM chính đang lỗi hoặc hết hạn mức</span>}
        </div>
      )}
    </div>
  );
}

export default function Chat({ home = false }: { home?: boolean }) {
  const { sid } = useParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const sessions = useQuery({ queryKey: ["chat-sessions"], queryFn: () => api<{ id: number; title: string }[]>("/chat/sessions") });
  const [turns, setTurns] = useState<Turn[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [hist, setHist] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const location = useLocation();
  const sessionId = sid ? Number(sid) : null;

  useEffect(() => {
    if (!sessionId) {
      setTurns([]);
      return;
    }
    if (busy) return;
    api<{ messages: ServerMsg[] }>(`/chat/sessions/${sessionId}`).then((s) => setTurns(fromServer(s.messages))).catch(() => nav("/chat"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  useEffect(() => {
    // Khong tra ve ket qua: Chromium moi tra Promise tu scrollIntoView -> React tuong la ham cleanup
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns]);

  // "Hỏi lại" từ thẻ đề xuất: điền sẵn ngữ cảnh vào ô nhập (sự kiện khi đang ở trang chat, router state khi đến từ trang khác)
  const draftIn = (d: string) => {
    setText(d);
    inputRef.current?.focus();
  };
  useEffect(() => {
    const onAsk = (e: Event) => {
      const d = (e as CustomEvent<AskDetail>).detail;
      d.handled = true;
      draftIn(d.text);
    };
    window.addEventListener(ASK_EVENT, onAsk);
    return () => window.removeEventListener(ASK_EVENT, onAsk);
  }, []);
  useEffect(() => {
    const draft = (location.state as { draft?: string } | null)?.draft;
    if (draft) {
      draftIn(draft);
      nav(location.pathname, { replace: true, state: null });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.state]);

  // Dự phòng khi LLM lỗi/hết hạn mức/chưa cấu hình: tra thẳng số liệu bằng tool đọc, không qua LLM (không lưu vào hội thoại)
  const showQuick = async (quick: string) => {
    try {
      const r = await api<{ title: string; ui: ({ type: "widget" } & WidgetSpec)[] }>(`/chat/quick/${encodeURIComponent(quick)}`);
      const blocks: Block[] = [
        { kind: "text", text: `Ops Chest chưa trả lời được lúc này, đây là số liệu tra cứu trực tiếp: **${r.title}**.` },
        ...r.ui.map((u): Block => ({ kind: "widget", spec: widgetSpec(u) })),
      ];
      setTurns((t) => [...t, { role: "assistant", blocks }]);
    } catch {
      /* không có dự phòng thì giữ nguyên thông báo lỗi */
    }
  };

  const send = async (msg: string, quick?: string) => {
    if (!msg.trim() || busy) return;
    setBusy(true);
    setText("");
    let failed = false;
    let id = sessionId;
    try {
      if (!id) {
        const s = await api<{ id: number }>("/chat/sessions", { method: "POST", body: {} });
        id = s.id;
        nav(`/chat/${id}`, { replace: true });
      }
      setTurns((t) => [...t, { role: "user", blocks: [{ kind: "text", text: msg }] }, { role: "assistant", blocks: [] }]);
      await streamChat(id, msg, (e) => {
        if (e.type === "error") failed = true;
        setTurns((t) => {
          const copy = [...t];
          copy[copy.length - 1] = apply(copy[copy.length - 1], e);
          return copy;
        });
      });
    } catch (e) {
      failed = true;
      setTurns((t) => [...t, { role: "assistant", blocks: [{ kind: "text", text: `⚠️ ${(e as Error).message}` }] }]);
    } finally {
      if (failed && quick) await showQuick(quick);
      setBusy(false);
      qc.invalidateQueries({ queryKey: ["chat-sessions"] });
      qc.invalidateQueries({ queryKey: ["pending-count"] });
      qc.invalidateQueries({ queryKey: ["proposals", "inbox"] });
      qc.invalidateQueries({ queryKey: ["briefing"] });
    }
  };

  // Lệnh nhanh: thẻ hiện ngay (không chờ LLM) và được backend ghi vào hội thoại như một lượt tra dữ liệu
  const command = async (key: string) => {
    if (busy) return;
    setBusy(true);
    let id = sessionId;
    try {
      if (!id) {
        const s = await api<{ id: number }>("/chat/sessions", { method: "POST", body: {} });
        id = s.id;
        nav(`/chat/${id}`, { replace: true });
      }
      const r = await runCommand(id, key);
      const blocks: Block[] = [];
      for (const e of r.ui) {
        if (e.type === "widget") blocks.push({ kind: "widget", spec: widgetSpec(e) });
        else if (e.type === "proposal") blocks.push({ kind: "proposal", proposal: e.proposal });
        else if (e.type === "chart") blocks.push({ kind: "chart", spec: e.spec });
      }
      if (r.error && !blocks.length) blocks.push({ kind: "text", text: `⚠️ ${r.error}` });
      setTurns((t) => [...t, { role: "user", blocks: [{ kind: "text", text: `▸ ${r.label}` }] }, { role: "assistant", blocks }]);
    } catch (e) {
      setTurns((t) => [...t, { role: "assistant", blocks: [{ kind: "text", text: `⚠️ ${(e as Error).message}` }] }]);
    } finally {
      setBusy(false);
      qc.invalidateQueries({ queryKey: ["chat-sessions"] });
      qc.invalidateQueries({ queryKey: ["pending-count"] });
      qc.invalidateQueries({ queryKey: ["proposals", "inbox"] });
    }
  };
  // Nơi khác (bản tin, thẻ) mở việc trong chat qua sự kiện này
  const commandRef = useRef(command);
  commandRef.current = command;
  useEffect(() => {
    const on = (e: Event) => commandRef.current((e as CustomEvent<string>).detail);
    window.addEventListener(COMMAND_EVENT, on);
    return () => window.removeEventListener(COMMAND_EVENT, on);
  }, []);

  const del = async (id: number) => {
    await api(`/chat/sessions/${id}`, { method: "DELETE" });
    qc.invalidateQueries({ queryKey: ["chat-sessions"] });
    if (id === sessionId) nav("/chat");
  };

  // Danh sách hội thoại: cột cố định bên trái (màn rộng) và nút thả xuống (màn hẹp) dùng chung
  const historyList = (onPick?: () => void) => (
    <>
      <button className="primary new-chat" onClick={() => { onPick?.(); nav("/chat"); }}>+ Hội thoại mới</button>
      {sessions.data?.length === 0 && <p className="muted small history-empty">Chưa có hội thoại nào.</p>}
      {sessions.data?.map((s) => (
        <div key={s.id} className={`item ${s.id === sessionId ? "on" : ""}`}>
          <button className="title" onClick={() => { onPick?.(); nav(`/chat/${s.id}`); }} title={s.title}
            aria-current={s.id === sessionId ? "page" : undefined}>
            {s.title}
          </button>
          <button className="icon sm ghost del" onClick={() => del(s.id)} aria-label={`Xóa hội thoại ${s.title}`} title="Xóa hội thoại">✕</button>
        </div>
      ))}
    </>
  );

  return (
    <div className="chat-shell">
    <aside className="chat-history" aria-label="Lịch sử hội thoại">
      <div className="section-title">Lịch sử hội thoại</div>
      {historyList()}
    </aside>
    <div className={`chat ${home ? "in-home" : ""}`}>
      <div className="chat-head">
        <button className="ghost sm" onClick={() => setHist((h) => !h)} aria-expanded={hist} aria-haspopup="true">
          Lịch sử hội thoại
        </button>
        {hist && (
          <div className="history" role="menu">
            {historyList(() => setHist(false))}
          </div>
        )}
      </div>
      <div className="messages">
        <div className="col">
          {turns.length === 0 && home && <Briefing onAsk={send} onCommand={openTask} disabled={busy} />}
          {turns.length === 0 && !home && (
            <div className="hello">
              <h1>Ops Chest có thể giúp gì hôm nay?</h1>
              <p>Hỏi về tồn kho, hạn sử dụng, chi phí, hoặc nhờ lên đơn đặt hàng.</p>
            </div>
          )}
          <div className="thread">
            {turns.map((t, i) =>
              t.role === "user" ? (
                <div key={i} className={`msg user ${(t.blocks[0] as { text: string }).text.startsWith("▸ ") ? "cmd" : ""}`}>
                  {(t.blocks[0] as { text: string }).text}
                </div>
              ) : (
                <AssistantTurn key={i} turn={t} streaming={busy && i === turns.length - 1} />
              ),
            )}
          </div>
          <div ref={endRef} />
        </div>
      </div>
      <div className="composer-wrap">
        <div className="composer-in">
          <TaskMenu />
          <form
            className="composer"
            onSubmit={(e) => {
              e.preventDefault();
              send(text);
            }}
          >
            <textarea
              ref={inputRef}
              rows={1}
              value={text}
              placeholder="Hỏi về tồn kho, hạn dùng, đơn hàng…"
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send(text);
                }
              }}
              aria-label="Tin nhắn"
            />
            <button className="primary" disabled={busy || !text.trim()}>
              Gửi
            </button>
          </form>
          <div className="foot-note">Ops Chest chỉ đề xuất. Anh/chị là người quyết định cuối cùng.</div>
        </div>
      </div>
    </div>
    </div>
  );
}
