# Ops Chest

Agent dạng chatbot (chat là giao diện chính, dashboard chỉ để tham khảo) giúp **Store Manager** của cửa hàng tiện lợi độc lập quản lý tồn kho theo lô và hạn sử dụng (HSD). Agent hỗ trợ:

- đề xuất đơn đặt hàng;
- xử lý hàng cận date (giảm giá, trả nhà cung cấp, ghi hủy);
- đề xuất ngừng nhập mặt hàng;
- trò chuyện kèm biểu đồ, bảng và thẻ số liệu ngay trong khung chat; nhận hàng bằng form trong chat; sửa đề xuất bằng lời ("giảm còn 30 thùng").

**Mọi quyết định cuối cùng thuộc về Store Manager (Human-in-the-loop).** Ops Chest chỉ *đề xuất*. Đặt hàng, gửi email, đổi giá, ghi hủy và ngừng nhập chỉ xảy ra khi Store Manager bấm duyệt.

> Đây là đồ án/demo. Dữ liệu là **giả lập**: 1 cửa hàng, 263 SKU, 10 nhà cung cấp, 365 ngày. Thương hiệu, nhà cung cấp và email đều là tên hư cấu (`*.test`). Mọi email đều rơi vào hộp thư sandbox Mailpit, không gửi ra Internet.

## Chạy nhanh (Docker)

```bash
cp .env.example .env        # điền LLM_API_KEY (bất kỳ endpoint OpenAI-compatible nào)
docker compose up -d --build
```

| Dịch vụ | Địa chỉ |
|---|---|
| Giao diện | http://localhost:5173 |
| API + tài liệu OpenAPI | http://localhost:8000/docs |
| Hộp thư sandbox (đơn hàng PDF gửi tới đây) | http://localhost:8025 |

- Lần chạy đầu, backend tự migrate schema (Alembic) và seed 365 ngày dữ liệu giả lập, mất khoảng 20 giây.
- Tài khoản demo ghi trong `.env.example`: một Store Manager (được duyệt) và một nhân viên (chỉ xem, chat, nhận hàng).
- Muốn demo ổn định theo một ngày cố định, đặt `SIM_TODAY` trong `.env` rồi seed lại:

  ```bash
  docker compose exec backend python -m app.sim.seed --reset
  ```

## Chạy không cần Docker (backend)

```bash
cd backend
uv sync
uv run python -m app.sim.seed --reset      # SQLite ./ops_chest.db
uv run uvicorn app.api.main:app --reload
uv run pytest -q                            # 72 test: engine, HITL, API, widget, bản tin, backtest
```

Frontend chạy bằng `cd frontend && npm install && npm run dev` (Node 20+). Email cần một SMTP ở `localhost:1025`, ví dụ chạy riêng Mailpit:

```bash
docker run -p 8025:8025 -p 1025:1025 axllent/mailpit
```

## Kiến trúc

```
React (Vite, Recharts, TanStack Query)
   │ REST + SSE (stream chat)
FastAPI
 ├─ agent/      LLM client OpenAI-compatible, 21 tool (15 đọc, 6 tạo đề xuất), vòng lặp tự viết
 ├─ engines/    dự báo, đặt hàng (newsvendor/order-up-to + trần HSD), rủi ro hết hạn, xử lý cận date,
 │              ABC-XYZ, KPI. Thuần Python, tất định, có unit test
 ├─ services/   đọc DB → gọi engine (dùng chung cho API, agent, job)
 ├─ proposals/  builders (tạo PENDING) · service (duyệt/sửa/từ chối) · executor (thực thi sau khi duyệt)
 ├─ notify/     email SMTP + PDF đơn hàng (reportlab, font tiếng Việt)
 ├─ jobs/       06:30 quét sáng (đơn hàng, cận date, quá hạn), 17:00 giờ vàng
 └─ sim/        bộ giả lập cửa hàng + seed + backtest A/B
PostgreSQL (SQLite khi dev/test) · Alembic · Mailpit
```

### HITL được bảo đảm bằng kiến trúc, không bằng prompt

1. LLM chỉ có tool loại `read` và `propose`. **Không có tool thực thi nào**. Test `test_tool_registry_has_no_execution_tools` kiểm tra điều này.
2. `propose_*` chỉ ghi bản ghi `Proposal` trạng thái `PENDING`.
3. Thực thi chỉ chạy qua `POST /api/proposals/{id}/approve`. Endpoint này yêu cầu role `manager` và kiểm tra trạng thái (`PENDING`/`FAILED`, chưa hết hiệu lực).
4. Thứ tự thực thi: ghi DB trước, gửi email cuối cùng. Email lỗi thì toàn bộ được rollback, đề xuất chuyển `FAILED` và Store Manager có thể duyệt lại.
5. Store Manager sửa được số lượng hoặc mức giảm giá trước khi duyệt. Phần sửa được lưu lại (`sm_edits`) để đo mức độ tin cậy của agent.
6. Mọi hành động đều ghi vào `audit_log`.

Test `test_agent_can_only_propose_never_execute` cho một LLM giả cố gọi `approve_proposal` và `send_email`. Kết quả: cả hai lời gọi đều bị báo lỗi, đề xuất vẫn `PENDING`, không có email nào được gửi.

### LLM: đổi provider bằng `.env`

```
LLM_BASE_URL=...   LLM_API_KEY=...   LLM_MODEL=...   LLM_STREAM=true|false
```

Dùng được với OpenAI, Groq, Gemini, OpenRouter, DeepSeek, Ollama, vLLM… và bất kỳ dịch vụ nào cung cấp `/v1/chat/completions` hỗ trợ `tools`.

**LLM phụ (fallback, tuỳ chọn):** đặt `LLM_BASE_URL_FALLBACK`, `LLM_API_KEY_FALLBACK`, `LLM_MODEL_FALLBACK`.

- Khi LLM chính lỗi (429 hết hạn mức, 5xx, mất kết nối) *trước khi* trả ra chữ nào, agent chuyển sang LLM phụ.
- LLM chính được "nghỉ" 2 phút khi hết hạn mức theo phút, 15 phút khi hết hạn mức theo ngày.
- Đã trả lời dở dang mà lỗi thì không đổi model giữa chừng, tránh một câu trả lời ghép từ hai model.
- Giao diện chat ghi rõ model nào đã trả lời từng lượt.
- Client tự xử lý khác biệt giữa các provider:
  - Groq kiểm tra schema rất nghiêm, nên tham số tùy chọn được khai báo cho phép `null`.
  - Gemini không nhận kiểu `["string","null"]`, nên schema gửi cho Gemini bỏ phần `null`.
  - Gemini 3 bắt buộc gửi lại `thought_signature` của từng tool call, nên client giữ lại trường này.
  - Gemini không gửi `index` cho tool call song song, nên client tự đánh số theo id.

**Token mỗi lượt:** prompt hệ thống và mô tả tool viết bằng tiếng Anh (chữ Việt có dấu tốn khoảng 3 lần token), nhưng agent vẫn trả lời tiếng Việt. Kết quả tool được nén (bỏ trường rỗng, JSON gọn, cắt danh sách dài). Kết quả tool của các lượt trước chỉ giữ phần đầu. Đo thật trên Groq, request đầu giảm từ khoảng 3.500 xuống 1.641 token. "OpenAI-compatible" chỉ bảo đảm cùng định dạng API; chất lượng tool calling và tiếng Việt khác nhau nhiều giữa các provider. Để chọn model:

```bash
uv run python -m app.agent.evals --json ket-qua-<model>.json
```

Bộ eval có 30 câu hỏi tiếng Việt và chấm các tiêu chí: gọi đúng tool, không bịa số (mọi con số phải có trong output của tool), không nói như đã thực thi, và không bỏ qua bước duyệt. Với các câu của giao diện chat-first, eval chấm thêm: tool phát đúng loại widget, agent không chép lại số trong bảng, và không nói "đã nhận hàng" (agent chỉ mở được form, nhân viên tự bấm xác nhận). Eval cần LLM thật nên chưa có điểm số trong repo; chạy lệnh trên với key của bạn.

### Giao diện chat-first

- **Trợ lý** là trang chủ: bản tin đầu ngày (dựng từ dữ liệu thật, **không qua LLM**), khung chat, hộp đề xuất để duyệt tại chỗ. Các trang dữ liệu (Cận date, Đặt & nhận hàng, Phân tích…) và dashboard cũ (`/stats`) vẫn còn làm đường dự phòng.
- **Widget:** tool đọc tự phát bảng/thẻ KPI (`app/agent/widgets.py`) từ chính dữ liệu của tool, nên số liệu luôn khớp dữ liệu thật; LLM chỉ tóm tắt.
- **Sửa đề xuất:** `revise_proposal` tạo đề xuất *mới* chờ duyệt và chuyển bản cũ sang `SUPERSEDED`. Nút "Hỏi lại" trên thẻ đề xuất đưa ngữ cảnh vào chat.
- **Nhận hàng:** `open_receive_form` chỉ hiện form trong chat; việc ghi vẫn đi qua `POST /api/purchase-orders/{id}/receive` do người dùng bấm.
- **Khi LLM lỗi:** các mục bản tin và gợi ý nhanh gọi `GET /api/chat/quick/{khóa}`, chạy thẳng tool đọc (không LLM, không ghi gì) và hiện widget, nên app vẫn dùng được và demo không phụ thuộc LLM.

## Tài liệu

- [docs/nghiep-vu.md](docs/nghiep-vu.md): các quyết định nghiệp vụ, giả định, KPI và kết quả mô phỏng.
- [docs/demo.md](docs/demo.md): kịch bản demo khoảng 10 phút.
