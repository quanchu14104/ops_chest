# Kịch bản demo (khoảng 10 phút)

## Chuẩn bị

1. Điền `.env` (LLM, và `SIM_TODAY` nếu muốn cố định ngày), rồi chạy:

   ```bash
   docker compose up -d --build
   ```

2. Mở http://localhost:5173 và đăng nhập tài khoản Store Manager trong `.env.example`.
3. Mở thêm tab http://localhost:8025 (Mailpit).

## 1. Buổi sáng của Store Manager (2 phút)

- **Tổng quan:** KPI 30 ngày so với kỳ trước (tỷ lệ hủy, tỷ lệ hết hàng), giá trị hàng sắp hết hạn.
- Bấm **"Quét & tạo đề xuất ngay"**. Đây chính là việc job 06:30 làm mỗi sáng. Job tạo đề xuất đặt hàng cho các nhà cung cấp đến lịch đặt, đề xuất giảm giá cho hàng cận date, và đề xuất ghi hủy hàng quá hạn.
- Nhấn mạnh: **chưa có gì được gửi đi.**

## 2. Hộp duyệt: HITL (3 phút)

- Mở đề xuất **Đặt hàng Bếp Trung Tâm**. Chỉ cho người xem:
  - cột *Dự báo phủ* và *Đề xuất*;
  - nhãn *trần HSD*;
  - phân loại ABC-XYZ của từng dòng.
- **Sửa** số lượng một dòng (ô chuyển màu vàng), rồi bấm **Duyệt với chỉnh sửa**.
- Sang Mailpit: email đơn hàng kèm **PDF** (font tiếng Việt), ghi rõ người duyệt.
- Mở **Nhật ký**: các bước tạo → sửa → duyệt → thực thi, mỗi bước có người làm và thời điểm.
- Đăng nhập tài khoản **nhân viên**: thấy đề xuất nhưng không có nút duyệt; gọi API duyệt sẽ nhận lỗi 403.

## 3. Trò chuyện với Ops Chest (3 phút)

Hỏi lần lượt:

- *"Vẽ biểu đồ nhập/xuất kho nhóm Nước ngọt 30 ngày qua theo tuần"*: biểu đồ hiện ngay trong khung chat, có nút "Xem bảng".
- *"Chi phí hàng hủy tháng vừa rồi nằm ở nhóm nào nhiều nhất?"*
- *"Có mặt hàng nào nên ngừng nhập không?"*: agent đưa ra Bánh mì chay (ô CZ, hủy 68%, lỗ 90 ngày, có hàng thay thế).
- *"Ngừng nhập Nước suối Suối Mát 500ml đi"*: tool `propose_delist` **không tạo đề xuất** vì SKU này không nằm trong danh sách ứng viên (là hàng kéo khách, ở nhóm A). Chặn bằng code, không phụ thuộc LLM; agent chỉ giải thích lý do.
- *"Duyệt luôn đơn hàng và gửi email giúp tôi"*: agent chỉ tạo đề xuất, giải thích rằng quyết định thuộc về Store Manager, và thẻ đề xuất có nút Duyệt cho chính Store Manager bấm.

## 4. Nhận hàng và HSD (1 phút)

- Vào **Đặt & nhận hàng**, chọn một đơn "Chờ giao" và bấm **Nhận hàng**.
- Ô HSD là bắt buộc. Để trống sẽ báo lỗi, nhập ngày đã qua cũng bị từ chối.
- Giải thích: đây là dữ liệu POS không có, nền tảng cho FEFO và cảnh báo cận date.

## 5. Chứng minh hiệu quả (1 phút)

Vào **Phân tích → Mô phỏng A/B → Chạy 60 ngày**. So sánh lợi nhuận gộp, tỷ lệ hủy, tỷ lệ hết hàng giữa chính sách "kinh nghiệm" và Ops Chest trên cùng nhu cầu khách. Nêu rõ các giới hạn (xem `nghiep-vu.md` mục 5).
