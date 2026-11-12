# Kịch bản demo (khoảng 12 phút)

Cửa hàng demo dùng **nhu cầu thật** của điểm bán số 18 trong FreshRetailNet-50K: 164 mặt hàng tươi, 7 nhà cung cấp hư cấu. Hôm nay của hệ thống là **26/06/2024**. Tên hàng có dạng "Mặt hàng 412 · nhóm 3.10", vì FRN chỉ công bố mã số; giá, giá vốn và HSD là giả định (xem [ml-frn.md](ml-frn.md), mục 4).

## Chuẩn bị

1. Điền `.env` (khóa LLM), rồi chạy lệnh dưới. Lần đầu, backend tự nạp 90 ngày dữ liệu FRN, mất khoảng 10 giây.

   ```bash
   docker compose up -d --build
   ```

2. Mở http://localhost:5173 và đăng nhập tài khoản Store Manager trong `.env.example`.
3. Mở thêm tab http://localhost:8025 (Mailpit).
4. Muốn chạy lại demo từ đầu (sau khi tua nhanh), dùng lệnh:

   ```bash
   docker compose exec backend python -m app.sim.seed --reset
   ```

## 1. Buổi sáng của Store Manager (2 phút)

- Trang chủ **Trợ lý** hiện **bản tin đầu ngày**: số đề xuất chờ duyệt, lô cận date, nhà cung cấp đến lịch đặt, đơn đang chờ giao, hàng hết. Nhấn mạnh: bản tin dựng từ dữ liệu thật, **không qua LLM**, nên không thể bịa số.
- Bấm một dòng của bản tin, ví dụ *lô cận date*: bảng lô hiện ngay trong chat, kèm phương án xử lý tốt nhất. Agent chỉ tóm tắt 2–3 ý.
- Vào **Số liệu tổng quan**, bấm **"Quét & tạo đề xuất ngay"**. Đây là việc job 06:30 làm mỗi sáng: đề xuất đặt hàng cho nhà cung cấp đến lịch, giảm giá hàng cận date, ghi hủy hàng quá hạn.
- Nhấn mạnh: **chưa có gì được gửi đi.**
- Nếu hỏi về dòng "… mặt hàng đang hết hàng" (con số lớn): đây là tồn **buổi sáng trước khi nhận hàng**. Hàng tươi HSD 1–2 ngày bán gần hết trong ngày, và hàng mới đang trên đường giao (dòng "đơn hàng đang chờ giao"). Lịch sử 90 ngày được vận hành bằng chính sách "kinh nghiệm", nên hết hàng khoảng 30% số ngày–mặt hàng, sát với thực tế FRN (44% số ngày có giờ hết hàng).

## 2. Dự báo bằng mô hình học máy (2 phút)

- Mở một đề xuất **Đặt hàng** (ví dụ Nông sản Tân Phát, khoảng 80 mặt hàng). Các dòng có nhãn **LightGBM**: dự báo do mô hình học trên 848 điểm bán FRN khác tính ra, không phải do engine EWMA cũ.
- Nhấn mạnh hai điều:
  - **Mô hình chỉ dự báo, không quyết định.** Số lượng đặt vẫn do engine tất định tính, với trần HSD, sức chứa và sàn mức phục vụ (nhãn *trần HSD*, *giữ ≥95%*). Mô hình không thể đề xuất vượt các giới hạn này (có test kiểm).
  - **Mô hình được chọn theo bằng chứng.** Nhóm hàng nào mô hình không thắng engine cũ trên các điểm bán giữ lại thì vẫn dùng EWMA. Với cửa hàng demo, cả 164 mặt hàng đều thuộc nhóm mô hình thắng.
- Vào **Phân tích → Dự báo nhu cầu bằng LightGBM trên dữ liệu thật**:
  - bảng 5 phương pháp: LightGBM WAPE 30,2% so với EWMA 35,1%, độ phủ khoảng 80% là 81% so với 73%;
  - bảng theo nhóm hàng, có nhãn "Dùng ML" / "Giữ engine cũ";
  - kiểm tra khôi phục nhu cầu ngày hết hàng (sai số 20,5% so với 32,3% nếu coi số bán là nhu cầu).
- Nói thẳng kết quả âm: **FRN không cho ước lượng được độ co giãn khi giảm giá** (ra con số phi lý e ≈ 9,6 vì giá nội sinh), nên OC giữ giả định cũ. Bảng ước lượng có trên trang để hội đồng thấy.

## 3. Hộp duyệt: HITL (2 phút)

- Trong thẻ đặt hàng: cột *Dự báo phủ*, *Đề xuất*, phân loại ABC-XYZ của từng dòng.
- **Sửa bằng lời:** nói với agent *"giảm mỗi món còn một nửa"*, hoặc bấm **Hỏi lại** trên thẻ. Agent tạo đề xuất **mới** chờ duyệt, bản cũ chuyển sang "Đã có bản sửa". Agent không tự duyệt.
- **Sửa bằng tay:** đổi số lượng một dòng (ô chuyển màu vàng), rồi bấm **Duyệt với chỉnh sửa**. Sang Mailpit xem email đơn hàng kèm **PDF** (font tiếng Việt), ghi rõ người duyệt.
- Mở **Nhật ký**: các bước tạo → sửa → duyệt → thực thi, mỗi bước có người làm và thời điểm.
- Đăng nhập tài khoản **nhân viên**: thấy đề xuất nhưng không có nút duyệt; gọi API duyệt nhận lỗi 403.

## 4. Trò chuyện với Ops Chest (2 phút)

Hỏi lần lượt:
- *"Tổng quan tồn kho hiện giờ"*: thẻ KPI và bảng theo nhóm hàng hiện trong chat.
- *"Vẽ biểu đồ nhập/xuất kho Nhóm tươi 6 30 ngày qua theo tuần"*: biểu đồ hiện ngay trong khung chat.
- *"Có mặt hàng nào nên ngừng nhập không?"*: agent đưa ra các mặt hàng ô CY hủy nhiều, ví dụ Mặt hàng 536 (nhóm 0.5, hủy khoảng 30%).
- *"Ngừng nhập Mặt hàng 70 đi"*: đây là hàng kéo khách (thuộc 5 mặt hàng bán nhiều nhất cửa hàng), nên `propose_delist` **không tạo đề xuất**. Chặn bằng code, không phụ thuộc LLM.
- *"Duyệt luôn đơn hàng và gửi email giúp tôi"*: agent chỉ tạo đề xuất và giải thích quyết định thuộc về Store Manager.

**Mẹo khi LLM chậm hoặc lỗi:** các mục bản tin và gợi ý nhanh có đường dự phòng không cần LLM.

## 5. Nhận hàng, rút kệ, kiểm date (2 phút)

- Nói trong chat *"Nhận đơn hàng đang chờ giao"*: agent **chỉ mở form**; nhân viên điền số thực nhận và HSD rồi tự bấm xác nhận.
- Trang **Đặt & nhận hàng**: form đầy đủ (tách dòng thành nhiều HSD, số từ chối kèm lý do, giá hóa đơn). HSD còn dưới 2/3 vòng đời thì tài khoản nhân viên bị chặn.
- Trang **Hàng cận date → Rút kệ cuối ngày**: ghi số thực gỡ rồi xác nhận (không cần duyệt). Store Manager chỉ duyệt bút toán ghi hủy.
- Giờ giảm giá cuối ngày lấy theo **khung bán thật của từng nhóm trong FRN**: nhóm bán đỉnh buổi sáng giảm từ 11h, nhóm bán đỉnh buổi tối giảm từ 18h.

## 6. Tua nhanh và giả thuyết (1 phút, tùy chọn)

- Nói *"Thứ Bảy này nhóm tươi 6 bán gấp rưỡi"* (nêu rõ ngày), rồi duyệt đề xuất giả thuyết.
- **Số liệu tổng quan → Tua nhanh**: tua được tối đa **7 ngày** (hết dữ liệu FRN vào 02/07/2024; tua quá sẽ báo lỗi rõ ràng). Nhu cầu trong 7 ngày này là nhu cầu thật mà mô hình chưa từng thấy.
- Tua nhanh **không tự duyệt**: không ai duyệt đơn thì kệ trống dần, lô đã rút kệ nằm chờ ghi hủy.

## 7. Chứng minh hiệu quả (1 phút)

Vào **Phân tích → Backtest A/B trên các điểm FRN**. Ba chính sách chạy trên **cùng nhu cầu thật** của 50 điểm bán giữ lại, trong 37 ngày mà mô hình backtest chưa từng thấy:
- **A:** làm theo kinh nghiệm, có giờ vàng;
- **B-EWMA:** Ops Chest với engine cũ;
- **B-ML:** Ops Chest với LightGBM.

Đọc trung vị và khoảng tứ phân vị qua 50 điểm, tỷ lệ số điểm B tốt hơn A, và bảng độ nhạy (khách phản ứng yếu hơn, Store Manager chỉ duyệt 60–80%, tắt sàn mức phục vụ…). Nói rõ: nhu cầu là thật, nhưng giá, HSD và phản ứng với giảm giá vẫn là giả định.

Nói thẳng kết quả ([ml-frn.md](ml-frn.md), mục 5.6):
- Ops Chest lãi hơn cách làm theo kinh nghiệm khoảng **+4%** (trung vị) và giảm hết hàng; với hàng kéo khách, hết hàng giảm từ 8,7% xuống 2,7%.
- **LightGBM dự báo chính xác hơn nhưng không lãi hơn EWMA**: chỉ thắng ở 34% số điểm, thua ở điểm bán nhỏ. Nó giảm hết hàng nhưng đặt dư hơn nên hủy nhiều hơn.
- Bài học: thước đo của dự báo (WAPE) và thước đo của quyết định (lãi) không trùng nhau. Bộ chọn mô hình nên chọn theo kết quả quyết định, đó là hướng làm tiếp.
