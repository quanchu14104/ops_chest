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
- Hoặc vào **Đặt & nhận hàng**, chọn một đơn "Chờ giao" và bấm **Nhận hàng** (cùng một endpoint). Form đầy đủ ở trang này: bấm **+ HSD** để tách một dòng thành hai lô có hai HSD, nhập số **từ chối** kèm lý do, nhập **giá hóa đơn** nếu khác đơn.
- Ô HSD là bắt buộc. Để trống sẽ báo lỗi, nhập ngày đã qua cũng bị từ chối. Nhập HSD còn ít hơn 2/3 vòng đời bằng tài khoản nhân viên: bị chặn; chỉ Store Manager tick xác nhận mới nhận được.
- Nhận thiếu so với đơn: kết quả báo giao thiếu và bản tin hôm sau có dòng "Đơn … giao thiếu".
- Đơn quá ngày giao có nhãn "trễ N ngày" và hiện trong bản tin. Store Manager bấm **Huỷ đơn** (bắt buộc ghi lý do) khi NCC không giao nữa; đơn chưa huỷ vẫn được tính là hàng đang về nên không bị đặt trùng.
- Giải thích: đây là dữ liệu POS không có, nền tảng cho FEFO và cảnh báo cận date. Nguyên tắc chung: LLM không có quyền ghi, mọi thao tác ghi là một cú bấm của con người.

## 4b. Giả thuyết, tua nhanh, học từ phần sửa (3 phút, tùy chọn)

- Nói trong chat: *"Thứ Bảy này có trận bóng, nhóm Bia bán gấp rưỡi"* (nêu rõ ngày). Thẻ đề xuất hiện dự báo trước và sau. Bấm **Duyệt**.
- Vào **Số liệu tổng quan → Tua nhanh → Tua 7 ngày**. Giả thuyết được chấm đúng/sai và hiện trong bản tin. Bỏ chọn "Giả thuyết đang áp dụng xảy ra đúng" để xem trường hợp sai.
- Nhấn mạnh: tua nhanh **không tự duyệt**. Nếu không ai duyệt đơn hàng, kệ trống dần và các lô đã rút kệ nằm chờ ghi hủy.
- Bấm **Nạp lịch sử sửa mẫu**: thẻ "Học từ cách anh/chị sửa đơn" hiện thói quen và nút đề xuất hệ số.
- Vào **Kiểm kê → Kiểm date theo HSD**: phiếu chỉ có các HSD trên sổ, không có số lượng. Nhập số theo từng HSD, bấm **Thêm HSD** cho một ngày sổ chưa có: đề xuất điều chỉnh cấp lô hiện ra, lô đó xuất hiện trong báo cáo cận date sau khi duyệt. Tab **Kiểm kê theo SKU** giữ cách đếm cũ.
- Vào **Hàng cận date**: thẻ **Rút kệ cuối ngày** liệt kê lô hết ngày bán. Ghi số thực gỡ rồi xác nhận: không cần duyệt, lô rời khỏi tồn ngay; Store Manager chỉ duyệt đề xuất ghi hủy (phần chênh với sổ ghi hao hụt). Chọn một lô và **Báo hủy** với lý do "Vỡ, móp" để thấy đề xuất hủy có lý do.
- Tua nhanh giả lập cả việc rút kệ của nhân viên, nên sau khi tua sẽ có đề xuất ghi hủy chờ duyệt.
- Trong form nhận hàng, bấm **Chụp HSD** để đọc tem bằng ảnh.
- Ngày đã tua được lưu lại. Muốn quay về, seed lại DB rồi khởi động lại backend.

## 5. Chứng minh hiệu quả (1 phút)

Vào **Phân tích → Mô phỏng A/B → Chạy 60 ngày**. So sánh lợi nhuận gộp, tỷ lệ hủy, tỷ lệ hết hàng giữa chính sách "kinh nghiệm" và Ops Chest trên cùng nhu cầu khách. Kéo xuống bảng **độ nhạy**: nhấn mạnh rằng giả lập cố tình cho khách phản ứng với giảm giá yếu hơn engine tin, và kết quả vẫn dương ở mọi kịch bản. Nói thẳng đánh đổi là hết hàng cao hơn (xem `nghiep-vu.md` mục 5).
