# Ops Chest

Agent dạng chatbot (chat là giao diện chính, dashboard chỉ để tham khảo) giúp **Store Manager** của cửa hàng tiện lợi độc lập quản lý tồn kho theo lô và hạn sử dụng (HSD). Agent hỗ trợ:

- đề xuất đơn đặt hàng;
- xử lý hàng cận date (giảm giá, trả nhà cung cấp, ghi hủy);
- đề xuất ngừng nhập mặt hàng;
- trò chuyện kèm biểu đồ, bảng và thẻ số liệu ngay trong khung chat; mở **thẻ việc** ngay trong chat (hộp duyệt, lô cận date, đơn chờ giao, phiếu trả NCC, form nhận hàng, kiểm kê, kiểm date, rút kệ); sửa đề xuất bằng lời ("giảm còn 30 thùng", "đặt thêm 50");
- ghi nhận giả thuyết về nhu cầu ("thứ Bảy có trận bóng, bia bán gấp rưỡi") và chấm đúng/sai sau sự kiện;
- học thói quen sửa đơn của Store Manager; kiểm kê đếm mù; đọc HSD từ ảnh tem.

**Mọi quyết định cuối cùng thuộc về Store Manager (Human-in-the-loop).** Ops Chest chỉ *đề xuất*. Đặt hàng, gửi email, đổi giá, ghi hủy và ngừng nhập chỉ xảy ra khi Store Manager bấm duyệt.

> Đây là đồ án/demo.
> - **Nhu cầu là dữ liệu thật** của bộ [FreshRetailNet-50K](https://huggingface.co/datasets/Dingdong-Inc/FreshRetailNet-50K) (Dingdong, giấy phép CC BY 4.0). Cửa hàng OC là điểm bán số 18 của FRN: 164 mặt hàng tươi, 90 ngày lịch sử, từ 28/03 đến 25/06/2024.
> - **Phần còn lại vẫn là giả định có ghi chú:** tên hàng (FRN chỉ có mã số), giá, giá vốn, hạn sử dụng, nhà cung cấp, và phần vận hành (lô, đơn, sổ sách).
> - Dự báo cho hàng tươi dùng mô hình **LightGBM huấn luyện trên Kaggle** với các điểm FRN khác. Mặt hàng nào dùng LightGBM, mặt hàng nào giữ EWMA được chọn **theo lãi trong backtest**, không theo sai số dự báo. Ngoài mẫu, dùng dự báo điểm của LightGBM với độ bất định của EWMA lãi hơn engine EWMA +0,8% (trung vị) và thắng ở 76% số điểm FRN giữ lại (chạy lại 12/11/2026). Xem [docs/ml-frn.md](docs/ml-frn.md), mục 5.6–5.7.
> - Thế giới giả lập cũ (263 SKU, 365 ngày) chỉ còn dùng cho bộ test quy tắc nghiệp vụ (`--source synthetic`).
> - Tên nhà cung cấp và email đều là hư cấu (`*.test`). Mọi email đều rơi vào hộp thư sandbox Mailpit, không gửi ra Internet.

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

- Lần chạy đầu, backend tự migrate schema (Alembic) và nạp 90 ngày của điểm FRN demo, mất khoảng 10 giây. Đồng hồ hệ thống đặt ở ngày 26/06/2024. Tua nhanh được tối đa 7 ngày (hết dữ liệu FRN vào 02/07/2024).
- Tài khoản demo ghi trong `.env.example`: một Store Manager (được duyệt) và một nhân viên (chỉ xem, chat, nhận hàng).
- Muốn nạp lại dữ liệu từ đầu (ví dụ sau khi tua nhanh), chạy lệnh sau. Thêm `--source synthetic` để dùng thế giới giả lập cũ:

  ```bash
  docker compose exec backend python -m app.sim.seed --reset
  ```

- **Ghi đè danh mục lúc seed (tùy chọn, mặc định tắt):** đặt `CATALOG_OVERRIDES_PATH` trỏ tới file JSON `{"products": {sku: {name, unit_price}}, "suppliers": {code: {name, email}}}`. Lúc seed FRN, hàng được đổi tên và giá bán (giá vốn tính lại theo đúng tỷ lệ giá vốn/giá bán cũ), NCC được đổi tên và email, trước khi sinh 90 ngày lịch sử nên lịch sử dùng giá mới. Không đổi nhóm hàng, lead time, lịch giao, đơn tối thiểu hay thỏa thuận trả hàng. Dùng cho bản demo nối Ops Chest với kiosk Retail-AI (thư mục `bridge/` ở cấp workspace).

## Chạy không cần Docker (backend)

```bash
cd backend
uv sync
uv run python -m app.sim.seed --reset      # SQLite ./ops_chest.db, dữ liệu FRN
uv run uvicorn app.api.main:app --reload
uv run pytest -q                            # 279 test: engine, HITL, quy tắc nghiệp vụ, API, widget, lệnh chat, bản tin, backtest, FRN
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
 ├─ agent/      LLM client OpenAI-compatible, 35 tool (26 đọc, 9 tạo đề xuất), vòng lặp tự viết, guard chống bịa số
 ├─ engines/    dự báo, đặt hàng (newsvendor/order-up-to + trần HSD), rủi ro hết hạn, xử lý cận date,
 │              ABC-XYZ, KPI. Thuần Python, tất định, có unit test
 ├─ services/   đọc DB → gọi engine (dùng chung cho API, agent, job); bản tin, lệnh chat và truy vấn nhanh không qua LLM
 ├─ proposals/  builders (tạo PENDING) · service (duyệt/sửa/từ chối) · executor (thực thi sau khi duyệt)
 ├─ notify/     email SMTP + PDF đơn hàng (reportlab, font tiếng Việt)
 ├─ jobs/       06:30 quét sáng (đơn hàng, cận date, quá hạn), 17:00 giờ vàng
 ├─ ml/         mô hình LightGBM (FRN) + bộ dự báo; huấn luyện ở ml/kaggle/train_frn.py (chạy trên Kaggle)
 └─ sim/        nguồn nhu cầu FRN / giả lập + seed + backtest A/B nhiều điểm bán + tua nhanh demo
PostgreSQL (SQLite khi dev/test) · Alembic · Mailpit
```

### HITL được bảo đảm bằng kiến trúc, không bằng prompt

1. LLM chỉ có tool loại `read` và `propose`. **Không có tool thực thi nào**. Test `test_tool_registry_has_no_execution_tools` kiểm tra điều này. Lệnh chat chạy thẳng tool (`/command`, `/quick`) cũng chỉ được gọi tool `read`/`propose` và không import module thực thi.
2. `propose_*` chỉ ghi bản ghi `Proposal` trạng thái `PENDING`.
3. Thực thi chỉ chạy qua `POST /api/proposals/{id}/approve`. Endpoint này yêu cầu role `manager` và kiểm tra trạng thái (`PENDING`/`FAILED`, chưa hết hiệu lực).
4. Thứ tự thực thi: ghi DB trước, gửi email cuối cùng. Email lỗi thì toàn bộ được rollback, đề xuất chuyển `FAILED` và Store Manager có thể duyệt lại.
5. Store Manager sửa được số lượng hoặc mức giảm giá trước khi duyệt. Phần sửa được lưu lại (`sm_edits`) để đo mức độ tin cậy của agent.
6. Mọi hành động đều ghi vào `audit_log`.

Test `test_agent_can_only_propose_never_execute` cho một LLM giả cố gọi `approve_proposal` và `send_email`. Kết quả: cả hai lời gọi đều bị báo lỗi, đề xuất vẫn `PENDING`, không có email nào được gửi.

Guard (`agent/guard.py` và `orchestrator.py`) gắn cờ câu trả lời nêu số không có trong kết quả tool, câu nói như đã thực thi, và câu "Đã tạo đề xuất #N" khi đề xuất #N không do chính lượt đó tạo (ví dụ đề xuất do job quét sáng tạo từ trước).

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

**Khi LLM lỗi:** người dùng chỉ thấy một câu tiếng Việt dễ hiểu (chạm giới hạn lượt gọi, câu hỏi cần quá nhiều dữ liệu, mất kết nối, lỗi khác). Chi tiết của provider (org id, link thanh toán, thông báo tiếng Anh) chỉ ghi vào log. Lỗi "request too large" (413, vượt context) được thử lại **một lần** với ngữ cảnh gọn: chỉ giữ câu hỏi hiện tại, kết quả tool cắt còn 1.500 ký tự.

**Token mỗi lượt:** prompt hệ thống và mô tả tool viết bằng tiếng Anh (chữ Việt có dấu tốn khoảng 3 lần token), nhưng agent vẫn trả lời tiếng Việt. Kết quả tool được nén (bỏ trường rỗng, JSON gọn, cắt danh sách dài) và cắt ở **5.000 ký tự**. Lịch sử gửi cho LLM chỉ gồm **16 tin nhắn** gần nhất, và kết quả tool của các lượt trước chỉ giữ 400 ký tự đầu. Các giới hạn này giữ một lượt dưới hạn mức token/phút của gói LLM miễn phí (ví dụ Groq 8.000 TPM); widget trên giao diện vẫn hiện đủ dữ liệu. Đo thật trên Groq, request đầu giảm từ khoảng 3.500 xuống 1.641 token (đo khi còn 31 tool). "OpenAI-compatible" chỉ bảo đảm cùng định dạng API; chất lượng tool calling và tiếng Việt khác nhau nhiều giữa các provider. Để chọn model:

```bash
uv run python -m app.agent.evals --json ket-qua-<model>.json
```

Bộ eval hiện có 37 câu hỏi tiếng Việt (`app/agent/evals.py`) và chấm các tiêu chí: gọi đúng tool, không bịa số (mọi con số phải có trong output của tool), không nói như đã thực thi, và không bỏ qua bước duyệt. Với các câu của giao diện chat-first, eval chấm thêm: tool phát đúng loại widget, agent không chép lại số trong bảng, và không nói "đã nhận hàng" (agent chỉ mở được form, nhân viên tự bấm xác nhận). Eval cần LLM thật. Kết quả đã chạy nằm trong `docs/eval/` (mỗi model một DB riêng, tắt fallback). Hai lần chạy này dùng bộ **30 câu** cũ, trước khi thêm 7 câu cho quy tắc nghiệp vụ (rút kệ, kiểm date, báo hủy, lịch nghỉ NCC, phiếu trả, điểm NCC, lịch kiểm kê); chưa chạy lại trên bộ 37 câu:

| Model | Đạt | Đúng tool | Không bịa số | Không nói như đã thực thi | Đúng widget | Không lặp số widget |
|---|---|---|---|---|---|---|
| `openai/gpt-oss-20b` (Groq, 09/11/2026) | 27/30 | 26/30 | 28/30 | 30/30 | 6/6 | 17/17 |
| `gemini-3.5-flash-lite` (09/11/2026) | 25/30 | 28/30 | 28/30 | 30/30 | 6/6 | 19/21 |

- Groq, 3 câu không đạt: 2 câu không gọi tool, trong đó 1 câu còn nêu số không có trong kết quả tool; 1 câu khác nêu số không có trong kết quả tool.
- Gemini, 5 câu không đạt: 2 câu nêu số không có trong kết quả tool, 2 câu chép lại số trong widget, 1 câu lỗi 429 hết hạn mức.
- Mỗi model chỉ chạy 1 lần, nên chênh lệch 2 câu chưa đủ để kết luận model nào tốt hơn. Cả hai đều không có câu nào nói như đã thực thi.
- Bộ 37 câu chưa có câu nào cho 10 tool: 4 tool mở thẻ việc (`open_approval_inbox`, `open_expiring_panel`, `open_purchase_orders`, `open_supplier_returns`), giả thuyết (`propose_demand_hypothesis`, `list_demand_hypotheses`), hệ số đặt hàng (`get_order_edit_patterns`, `propose_order_adjustment`), `propose_dispose_expired` và `get_stock_flow`.

### Giao diện chat-first

- **Menu:** nhóm "Làm việc" chỉ có **Trợ lý** (trang chủ). **Hộp duyệt** là ngăn kéo bên phải (không còn trang riêng, không nằm ở thanh bên): tab Chờ duyệt / Lịch sử, chip lọc theo loại; nút Hộp duyệt ở thanh trên, ô "Duyệt" ở thanh đáy điện thoại, ô "Chờ duyệt" trong menu Công việc và dòng bản tin đều mở ngăn này, địa chỉ cũ `/approvals` cũng vậy. Các trang dữ liệu (Hàng cận date, Đặt & nhận hàng, Kiểm kê, Phân tích, Hàng hóa & NCC, Nhật ký) nằm trong nhóm **"Tra cứu"** thu gọn, để tra cứu và làm đường dự phòng. Không còn trang Tổng quan riêng (chỉ lặp lại thông tin trang khác): bản tin đầu ngày đóng vai trò đó; độ tin đề xuất, giả thuyết nhu cầu và học từ cách sửa đơn nằm cuối trang Phân tích. Menu tài khoản có **Cài đặt** (giao diện, trợ lý, báo cáo mô hình, **Tua nhanh (demo)**); báo cáo kỹ thuật về mô hình ở trang riêng `/model`. Trên điện thoại có thanh tab ở đáy (Trợ lý, Duyệt, Thêm).
- **Trang Trợ lý:** bản tin đầu ngày (dựng từ dữ liệu thật, **không qua LLM**) chia ba nhóm "Cần quyết", "Cần để ý", "Việc trong ngày", rồi đến khung chat. Bản tin theo vai trò: nhân viên thấy mục đề xuất chờ duyệt ở dạng thông tin ("chờ Store Manager duyệt"), không phải việc cần làm. Nhiều NCC đến lịch đặt thì gộp thành một dòng, tên từng NCC xem ở ô thông tin. Giá vốn rủi ro của lô cận date chỉ cộng đúng các lô được đếm.
- **Menu "Công việc"** cạnh ô chat: lưới nút to (Chờ duyệt, Cận date, Rút kệ, Kiểm date, Kiểm kê, Nhận hàng, Trả NCC, Hàng hết, KPI; Store Manager có thêm Quét đề xuất), kèm số đếm từ bản tin. Bấm một việc, hoặc bấm một dòng bản tin, mở việc đó trong **popup**, không qua LLM.
- **Thẻ việc sống trong chat:** các tool `open_approval_inbox`, `open_expiring_panel`, `open_purchase_orders`, `open_supplier_returns` phát thẻ `panel` (`app/agent/widgets.py`). Thẻ tự tải số liệu hiện tại và có nút thao tác thật (duyệt, giảm giá/trả NCC/ghi hủy theo lô chọn, nhận hàng, huỷ đơn), đi qua REST có kiểm quyền. Prompt yêu cầu agent mở đúng thẻ khi người dùng muốn làm việc, rồi trả lời tối đa 2 câu.
- **Lệnh chat không qua LLM:** `POST /api/chat/sessions/{id}/command` với một khóa (`pending`, `lots`, `pull`, `date_check`, `count_due`, `orders`, `receive:<PO>`, `returns`, `inventory`, `oos`, `kpi`, `hypotheses`, `order:<NCC>`, `scan`) chạy thẳng một tool và ghi vào hội thoại như một lượt agent gọi tool, nên tải lại lịch sử vẫn thấy thẻ và LLM ở lượt sau biết đã hiện gì. Chỉ chạy tool `read`/`propose`; `scan` chạy quét sáng (chỉ tạo đề xuất `PENDING`). Giao diện nghe sự kiện `opschest:command` để chèn thẻ vào luồng chat.
- **Widget:** tool đọc tự phát bảng/thẻ KPI từ chính dữ liệu của tool, nên số liệu luôn khớp dữ liệu thật; LLM chỉ tóm tắt.
- **Thẻ đề xuất:** tổng tiền ở đầu thẻ cập nhật theo phần sửa; đơn dài lọc được còn các dòng cần chú ý; thanh duyệt dính ở cuối thẻ; từ chối chọn lý do bằng chip. Đề xuất giảm giá thu về ít hơn phương án giữ giá thì có cảnh báo và phải bấm duyệt hai lần.
- **Sửa đề xuất:** `revise_proposal` tạo đề xuất *mới* chờ duyệt và chuyển bản cũ sang `SUPERSEDED`. Với đơn hàng, nhận số lượng mới (`sku_qty`) hoặc số đặt thêm (`sku_add`, "đặt thêm 50"), và thêm được mặt hàng cùng NCC chưa có trong đơn. "Soạn tờ trình đặt thêm…" vì thế thành một đề xuất thật chờ duyệt; prompt cấm viết đơn hay email dạng văn bản tự do và cấm bảo Store Manager tự liên hệ NCC. Nút "Hỏi lại" trên thẻ đề xuất đưa ngữ cảnh vào chat.
- **Hàng đang hết:** `search_products` với `out_of_stock=true` liệt kê mặt hàng hết hàng, bán chạy 28 ngày qua lên trước, nên "món nào đang hết" ra tên hàng, không chỉ con số.
- **Nhận hàng:** `open_receive_form` chỉ hiện form trong chat; việc ghi vẫn đi qua `POST /api/purchase-orders/{id}/receive` do người dùng bấm.
- **Điều khiển cảm ứng:** nút +/−, thanh trượt mức giảm giá, chip, công tắc, ô ngày dd/mm/yyyy; chữ phụ chuyển vào ô thông tin (i). Nhật ký hiện dạng dễ đọc, danh mục hàng có bộ lọc, KPI chia nhóm, bảng xếp chồng trên điện thoại.
- **Khi LLM lỗi:** bản tin, menu Công việc và gợi ý nhanh gọi `GET /api/chat/quick/{khóa}` (chạy thẳng tool đọc, không ghi gì) hoặc tự tải thẻ việc, nên app vẫn dùng được và demo không phụ thuộc LLM.

## Tài liệu

- [docs/nghiep-vu.md](docs/nghiep-vu.md): các quyết định nghiệp vụ, giả định, KPI và kết quả mô phỏng.
- [docs/demo.md](docs/demo.md): kịch bản demo khoảng 12 phút.
- [docs/ml-frn.md](docs/ml-frn.md): dữ liệu FreshRetailNet-50K, mô hình LightGBM, bộ chọn theo lãi và backtest A/B nhiều điểm bán.
- [docs/plan-sua-nghiep-vu.md](docs/plan-sua-nghiep-vu.md): kế hoạch sửa nghiệp vụ N1–N15 (10/11/2026) và trạng thái triển khai.
- [docs/eval/](docs/eval/): kết quả eval agent theo từng model.
