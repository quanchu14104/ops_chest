# Kịch bản demo (khoảng 10 phút)

## Chuẩn bị

1. Điền `.env` (LLM, và `SIM_TODAY` nếu muốn cố định ngày), rồi chạy:

   ```bash
   docker compose up -d --build
   ```

2. Mở http://localhost:5173 và đăng nhập tài khoản Store Manager trong `.env.example`.
3. Mở thêm tab http://localhost:8025 (Mailpit).

## 1. Buổi sáng của Store Manager (2 phút)

- Trang chủ **Trợ lý** hiện **bản tin đầu ngày**: số đề xuất chờ duyệt, lô cận date, nhà cung cấp đến lịch đặt, đơn đang chờ giao, hàng hết. Nhấn mạnh: bản tin dựng từ dữ liệu thật, **không qua LLM**, nên không thể bịa số.
- Bấm một dòng của bản tin, ví dụ *lô cận date*: bảng lô hiện ngay trong chat kèm phương án xử lý tốt nhất, agent chỉ tóm tắt 2–3 ý.
- Để có đề xuất mới ngay, vào **Số liệu tổng quan** và bấm **"Quét & tạo đề xuất ngay"**. Đây chính là việc job 06:30 làm mỗi sáng: đề xuất đặt hàng cho nhà cung cấp đến lịch, giảm giá hàng cận date, ghi hủy hàng quá hạn. Dashboard KPI 30 ngày cũng nằm ở đây.
- Nhấn mạnh: **chưa có gì được gửi đi.**

## 2. Hộp duyệt: HITL (3 phút)

- Mở đề xuất **Đặt hàng Bếp Trung Tâm** (trong hộp duyệt ở trang Trợ lý). Chỉ cho người xem:
  - cột *Dự báo phủ* và *Đề xuất*;
  - nhãn *trần HSD*;
  - phân loại ABC-XYZ của từng dòng.
- **Sửa bằng lời:** nói với agent *"giảm mỗi món còn một nửa"* hoặc bấm **Hỏi lại** trên thẻ. Agent tạo đề xuất **mới** chờ duyệt, bản cũ chuyển sang "Đã có bản sửa". Agent không tự duyệt.
- **Sửa bằng tay:** đổi số lượng một dòng (ô chuyển màu vàng), rồi bấm **Duyệt với chỉnh sửa**.
- Sang Mailpit: email đơn hàng kèm **PDF** (font tiếng Việt), ghi rõ người duyệt.
- Mở **Nhật ký**: các bước tạo → sửa → duyệt → thực thi, mỗi bước có người làm và thời điểm.
- Đăng nhập tài khoản **nhân viên**: thấy đề xuất nhưng không có nút duyệt; gọi API duyệt sẽ nhận lỗi 403.

## 3. Trò chuyện với Ops Chest (3 phút)

Hỏi lần lượt:

- *"Tổng quan tồn kho hiện giờ"*: thẻ KPI và bảng theo nhóm hàng hiện trong chat.
- *"Vẽ biểu đồ nhập/xuất kho nhóm Nước ngọt 30 ngày qua theo tuần"*: biểu đồ hiện ngay trong khung chat, có nút "Xem bảng".
- *"Chi phí hàng hủy tháng vừa rồi nằm ở nhóm nào nhiều nhất?"*
- *"Có mặt hàng nào nên ngừng nhập không?"*: agent đưa ra Bánh mì chay (ô CZ, hủy 68%, lỗ 90 ngày, có hàng thay thế).
- *"Ngừng nhập Nước suối Suối Mát 500ml đi"*: tool `propose_delist` **không tạo đề xuất** vì SKU này không nằm trong danh sách ứng viên (là hàng kéo khách, ở nhóm A). Chặn bằng code, không phụ thuộc LLM; agent chỉ giải thích lý do.
- *"Duyệt luôn đơn hàng và gửi email giúp tôi"*: agent chỉ tạo đề xuất, giải thích rằng quyết định thuộc về Store Manager, và thẻ đề xuất có nút Duyệt cho chính Store Manager bấm.

**Mẹo khi LLM chậm hoặc lỗi:** các mục bản tin và gợi ý nhanh có đường dự phòng không cần LLM. Nếu LLM trả lỗi, giao diện vẫn hiện số liệu tra cứu trực tiếp (bảng/thẻ KPI) thay vì chết trắng.

## 4. Nhận hàng và HSD (1 phút)

- Nói trong chat: *"Nhận đơn hàng đang chờ giao"*. Agent **chỉ mở form** nhận hàng trong chat (không tự nhận, và không bao giờ nói "đã nhận"). Điền số lượng thực nhận và HSD từng dòng rồi bấm xác nhận.
- Hoặc vào **Đặt & nhận hàng**, chọn một đơn "Chờ giao" và bấm **Nhận hàng** (cùng một endpoint).
- Ô HSD là bắt buộc. Để trống sẽ báo lỗi, nhập ngày đã qua cũng bị từ chối.
- Giải thích: đây là dữ liệu POS không có, nền tảng cho FEFO và cảnh báo cận date. Nguyên tắc chung: LLM không có quyền ghi, mọi thao tác ghi là một cú bấm của con người.

## 5. Chứng minh hiệu quả (1 phút)

Vào **Phân tích → Mô phỏng A/B → Chạy 60 ngày**. So sánh lợi nhuận gộp, tỷ lệ hủy, tỷ lệ hết hàng giữa chính sách "kinh nghiệm" và Ops Chest trên cùng nhu cầu khách. Nêu rõ các giới hạn (xem `nghiep-vu.md` mục 5).
