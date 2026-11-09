# Nghiệp vụ, giả định và KPI

## 1. Phạm vi: cửa hàng tiện lợi độc lập

Store Manager (SM) làm việc trực tiếp với đại lý, có toàn quyền nhập hoặc ngừng nhập mặt hàng. Mô hình này khác các chuỗi lớn (7-Eleven, FamilyMart, Circle K, GS25, WinMart+). Ở chuỗi, hợp đồng và danh mục hàng do tổng công ty quyết; cửa hàng chỉ đặt hàng về kho tổng (DC), hoặc đặt nhà cung cấp giao thẳng (DSD).

## 2. Các điều chỉnh so với ý tưởng ban đầu

| Ý tưởng ban đầu | Điều chỉnh trong Ops Chest | Lý do |
|---|---|---|
| "Niên hạn sản phẩm" | Quản lý theo **lô**, mỗi lô có HSD. Bước **nhận hàng bắt buộc nhập HSD**. Bán theo **FEFO** (hết hạn trước bán trước). | POS chỉ biết SKU, không biết HSD. Cùng một SKU có thể gồm nhiều lô. |
| Mọi mặt hàng như nhau | 3 nhóm vòng đời: FRESH (≤3 ngày), SHORT (≤30 ngày), LONG | Lãng phí tập trung ở hàng tươi; mỗi nhóm cần chính sách đặt hàng riêng. |
| "Quyết định abcxyz" | **Phân tích ABC-XYZ** (kỹ thuật có thật) | Ma trận 9 ô quyết định mức tồn an toàn và là cơ sở đề xuất ngừng nhập. |
| Tự động gửi "hợp đồng" | Agent chỉ soạn **đơn đặt hàng (PO)** theo mẫu cố định, kèm PDF. **Hợp đồng nguyên tắc** được lưu dưới dạng dữ liệu (chiết khấu, lead time, đơn tối thiểu, điều khoản đổi trả). | Hợp đồng ký mỗi năm một lần; đơn hàng gửi hằng ngày. LLM không nên soạn văn bản pháp lý. |
| Ngừng nhập dựa trên lịch sử bán | Chỉ xét ô C-Y/C-Z **và** (hủy ≥15% hoặc lỗ), **không bao giờ** đề xuất cắt hàng kéo khách (traffic driver), có kiểm tra hàng thay thế | Nước suối, mì gói lãi thấp nhưng thiếu là khách bỏ đi. |
| LLM "ra quyết định" | **Mọi con số do engine tất định tính.** LLM chỉ gọi tool, giải thích và trò chuyện. | LLM tính sai và không lặp lại được kết quả; cách này cũng kiểm chứng được khi bảo vệ. |

## 3. Engine (`backend/app/engines/`)

### Dự báo (`forecast.py`)

- Mức nền EWMA (half-life 14 ngày) × hệ số thứ trong tuần × hệ số Tết.
- Hệ số Tết được *học từ chính lịch sử SKU*.
- **Nhu cầu bị chặn (censored demand).** Ngày hết hàng thì doanh số bằng lượng tồn, còn nhu cầu thật lớn hơn. Nếu bỏ hẳn những ngày này thì dự báo **bị lệch thấp** (đã đo được khoảng −10% trên hàng tươi), vì đó thường là ngày bán chạy. Engine ước lượng `E[D | D ≥ doanh số]` theo phân phối chuẩn (kiểu Tobit) và lặp 3 vòng.
- **Doanh số nhờ giảm giá không phải nhu cầu.** Tính cả vào thì dự báo bị thổi lên, đặt dư, rồi lại phải giảm giá tiếp. Trong backtest, lượng bán giờ vàng bị bỏ khỏi chuỗi nhu cầu, lượng bán giảm giá cả ngày được chia cho `1 + co giãn × mức giảm` (`baseline_demand`). Lịch sử trong DB hiện chỉ sinh từ giai đoạn không giảm giá; khi nối POS thật, cần lấy thêm số lượng bán theo mức giảm.
- Sai số chuẩn (σ) tính trên mọi quan sát, có sàn Poisson (σ ≥ √mức nền).

### Số lượng đặt (`replenishment.py`)

Cả hai chế độ dưới đây đều:

- mô phỏng FEFO đến ngày hàng về, **chỉ tính phần tồn còn hạn** khi hàng mới về;
- trừ hàng đang về, kể cả đơn đã quá ngày giao. Đơn không giao nữa thì Store Manager hủy trên trang Đặt & nhận hàng; bản tin cảnh báo đơn trễ;
- bị **chặn trần theo HSD**: không đặt nhiều hơn lượng bán kịp trước khi lô mới hết hạn;
- làm tròn theo quy cách đóng gói.

**Hàng dễ hư** (HSD ≤ chu kỳ đặt + 7 ngày) dùng mô hình **newsvendor**:

```
mức phục vụ tối ưu = (giá − vốn + chi phí mất khách) / (giá − giá trị thu hồi + chi phí mất khách)
```

- *Chi phí mất khách* ("chance loss", khái niệm 7-Eleven Nhật hay nhấn mạnh) = 30% giá bán, và 100% với hàng kéo khách.
- *Giá trị thu hồi* = tiền kỳ vọng thu lại khi giảm giá giờ vàng hoặc trả nhà cung cấp.

**Hàng bền** dùng **order-up-to**, với tồn an toàn `z·σ·√(L+R)` và z theo ô ABC-XYZ:

| | X | Y | Z |
|---|---|---|---|
| **A** | 2,05 | 1,65 | 1,28 |
| **B** | 1,65 | 1,28 | 1,04 |
| **C** | 1,28 | 1,04 | 0,84 |

### Rủi ro hết hạn và xử lý cận date (`expiry.py`, `disposition.py`)

Engine mô phỏng bán FEFO theo dự báo để ra **số lượng dự kiến hủy** của từng lô, rồi so sánh **tiền thu hồi kỳ vọng** của các phương án:

- **Giữ nguyên:** phần dư bị hủy, tốn thêm chi phí xử lý khoảng 500đ/đơn vị.
- **Giảm giá 20/30/50%.** Hệ số co giãn giả định: FRESH 3,0, SHORT 2,0, LONG 1,2. Đây là giả định cần hiệu chỉnh bằng dữ liệu thật.
  - Lô hết hạn trong ngày: chỉ **giảm giá giờ vàng sau 18h cho phần còn dư** (khoảng 30% lượt khách), nên không ăn mất doanh thu giá gốc ban ngày. Khách buổi tối vốn sẽ trả giá gốc cũng được hưởng giá giảm; engine và bộ giả lập đều trừ phần này.
  - Lô còn vài ngày: giảm giá cả lô; engine tính cả phần doanh thu giá gốc bị mất.
  - Lô đang giảm giá: chỉ xét mức sâu hơn, so với phương án giữ mức hiện tại. Hệ thống không tăng giá trở lại, vì tem đã dán.
- **Trả nhà cung cấp:** chỉ khi thỏa thuận **còn hiệu lực** cho phép và lô còn ≥ N ngày trước HSD; hoàn x% giá vốn. Thỏa thuận hết hiệu lực thì đơn hàng không được chiết khấu và có cảnh báo.
- Một lô đang nằm trong đề xuất trả hoặc ghi hủy còn mở thì không được đề xuất lại cho đến khi đề xuất đó đóng.

### Giả thuyết của Store Manager (`services/hypotheses.py`)

Dự báo từ lịch sử không biết tuần này có trận bóng. Cách làm của 7-Eleven Nhật là để người bán đặt giả thuyết rồi kiểm chứng; đây cũng là việc chat làm tốt hơn dashboard.

- Store Manager nói trong chat, agent tạo đề xuất với **đúng hệ số và ngày người dùng nêu**. Thiếu thì agent phải hỏi, không tự chọn.
- Giới hạn bằng code: hệ số 0,3–3, tối đa 14 ngày, không trùng khoảng ngày cùng phạm vi.
- Dự báo chỉ đổi sau khi duyệt. Những ngày có sự kiện không được dùng để ước lượng mức nền, giống cách xử lý Tết.
- Hết khoảng ngày, hệ thống so lượng bán thực tế với dự báo nền đã lưu. **Đúng** nếu nhu cầu đi được ≥50% quãng đường dự đoán, **sai** nếu ≤25%, còn lại là đúng một phần. Dùng lượng bán vì cửa hàng thật không biết nhu cầu bị hụt. Khi từ 20% số SKU-ngày bị hết hàng, lượng bán chỉ là cận dưới của nhu cầu, nên hệ thống chỉ giữ kết luận mà cận dưới chứng minh được: giả thuyết tăng là "đúng", giả thuyết giảm là "sai". Các trường hợp còn lại chấm **chưa đủ căn cứ**, tránh việc nhập ít, bán ít rồi tự xác nhận là nhu cầu đã giảm.

### Học từ phần sửa (`engines/edit_learning.py`)

Chỉ gợi ý khi có ít nhất 5 lần sửa trên 3 đơn đã duyệt, trung vị lệch từ 15% và 70% số lần cùng chiều. Hệ số do code tính (làm tròn 0,05, trong khoảng 0,5–1,5), agent không chọn được. Áp dụng phải qua duyệt, tắt được bất cứ lúc nào. Hệ số tăng vẫn không vượt trần HSD.

### Kiểm kê (`services/stockcount.py`)

Đếm **mù**: phiếu không hiện số trên sổ, vì người đếm thấy số sẽ có xu hướng đếm cho khớp. Nhân viên gửi số đếm; chênh lệch thành đề xuất cho Store Manager duyệt. Thiếu thì trừ lô gần hết hạn trước (không biết mất ở lô nào), dư thì cộng vào lô mới nhất. Nếu tồn đã thay đổi giữa lúc đếm và lúc duyệt, đề xuất thất bại và phải đếm lại, thay vì ghi đè bằng số cũ.

### Đọc ảnh tem HSD (`agent/vision.py`)

Model chỉ đọc chữ in trên bao bì; việc hiểu ngày (ngày trước tháng, chỉ có tháng/năm thì lấy cuối tháng) do code tất định làm. Không đọc được HSD thì trả rỗng và không bao giờ lấy NSX thay thế. Kết quả chỉ điền sẵn ô HSD, người nhận hàng vẫn phải đối chiếu và xác nhận; ảnh không được lưu. Đã thử trên ảnh tem tự tạo, **chưa thử trên ảnh bao bì thật**.

## 4. Định nghĩa KPI (`kpi.py`)

| KPI | Công thức |
|---|---|
| Tỷ lệ hủy | giá vốn hàng hủy / (giá vốn hàng bán + giá vốn hàng hủy) |
| Tỷ lệ hết hàng | nhu cầu hụt / (đã bán + nhu cầu hụt) |
| Lợi nhuận gộp sau hủy | doanh thu − giá vốn bán − giá vốn hủy − giá vốn hàng trả + tiền NCC hoàn |
| Số ngày tồn | tồn kho trung bình (giá vốn) / giá vốn bán trung bình mỗi ngày |
| Mức tin cậy của agent | tỷ lệ đề xuất được duyệt, tỷ lệ bị sửa, mức sửa số lượng trung bình |
| Hao hụt kiểm kê | tổng giá trị các điều chỉnh âm; báo cáo riêng, chưa trừ vào lợi nhuận gộp |

Lưu ý: dữ liệu giả lập biết chính xác "nhu cầu hụt". Cửa hàng thật không biết số này, nên phải ước tính từ dự báo trong những ngày hết hàng.

## 5. Kết quả mô phỏng A/B (`python -m app.sim.backtest`)

Hai chính sách chạy trên cùng cửa hàng, với **cùng nhu cầu khách** (tất định theo seed):

- **A, "kinh nghiệm":** mức tồn = trung bình doanh số 4 tuần × hệ số an toàn; cuối ngày giảm 30% hàng hết hạn hôm nay. Không biết thứ trong tuần, Tết, hay việc doanh số bị chặn khi hết hàng.
- **B, Ops Chest:** coi như Store Manager duyệt mọi đề xuất.

**Thiết kế để kết quả không tự chứng minh:** hệ số co giãn của "thế giới giả lập" (`sim/world.py`) tách khỏi hệ số engine giả định. Ở kịch bản tham chiếu, khách chỉ phản ứng với giảm giá bằng 50% mức engine tin (FRESH 1,5 so với 3,0), nghĩa là engine cố tình bị sai mô hình. Chính sách B chỉ dùng thứ cửa hàng quan sát được.

Bảng dưới (08/09–06/11/2026, 60 ngày). Mỗi dòng chỉ đổi một điều so với dòng tham chiếu. Tạo lại bằng `python -m app.sim.backtest --sensitivity`, và cũng hiện trong trang **Phân tích**.

| Kịch bản | Lợi nhuận B so với A | Tỷ lệ hủy A / B | Hết hàng A / B |
|---|---|---|---|
| **Tham chiếu** | **+13,6%** | 11,0% / 6,5% | 5,6% / 7,3% |
| Nhu cầu khác (seed 11) | +13,5% | 11,3% / 7,0% | 5,4% / 7,2% |
| Nhu cầu khác (seed 23) | +11,7% | 10,8% / 6,6% | 5,0% / 7,2% |
| Khách phản ứng đúng 100% giả định | +15,3% | 10,5% / 5,2% | 5,1% / 7,3% |
| Khách chỉ phản ứng 25% giả định | +11,5% | 11,1% / 7,3% | 5,8% / 7,4% |
| B chỉ đặt hàng (tắt giảm giá, trả NCC) | +10,0% | 11,0% / 8,3% | 5,6% / 7,4% |
| B không tách doanh số giảm giá khỏi nhu cầu | +11,7% | 11,0% / 7,3% | 5,6% / 7,0% |
| Store Manager chỉ duyệt 80% đề xuất | +11,3% | 11,0% / 7,6% | 5,6% / 7,0% |
| Store Manager chỉ duyệt 60% đề xuất | +8,0% | 11,0% / 8,9% | 5,6% / 6,7% |
| 20% lượt mua lấy lô mới (không theo FEFO) | +13,7% | 11,1% / 6,6% | 5,6% / 7,3% |
| 50% lượt mua lấy lô mới (không theo FEFO) | +14,0% | 11,3% / 6,8% | 5,6% / 7,4% |
| Cách so sánh cũ (A không giảm giá, khách phản ứng đúng giả định) | +17,7% | 11,8% / 5,2% | 6,0% / 7,3% |

Con số nên trích dẫn là **khoảng +12–14% lợi nhuận gộp, tỷ lệ hủy giảm khoảng 40%**. Dòng "cách so sánh cũ" được giữ lại để cho thấy phương pháp so sánh ảnh hưởng tới kết quả ra sao.

Từ khi tính cả phần khách buổi tối được hưởng giá giảm, lợi nhuận của cả hai chính sách đều thấp đi. A giảm 30% mọi buổi tối nên mất nhiều hơn B, vì B bỏ qua các lần giảm không có lợi. Vì vậy chênh lệch tăng thêm khoảng 2 điểm, đồng thời tỷ lệ hủy của B cao hơn trước. Phần tăng này một phần đến từ việc baseline A cứng nhắc, không nên hiểu là engine tốt lên ngần ấy.

**Đánh đổi:** tỷ lệ hết hàng của B cao hơn A ở mọi kịch bản (5–6% so với khoảng 7%), và B giữ tồn kho nhiều hơn. Lợi nhuận tăng chủ yếu nhờ hủy ít hơn, không phải nhờ bán được nhiều hơn. Đây là điểm yếu còn lại của engine, dù newsvendor đã tính chi phí mất khách.

**Giới hạn cần nói rõ khi bảo vệ:**

1. Mô hình nhu cầu và hệ số co giãn đều là giả định; bảng độ nhạy chỉ cho biết kết luận chịu được sai lệch tới đâu.
2. Baseline A là một heuristic hợp lý, không phải hành vi đo được của một Store Manager thật.
3. Kịch bản tham chiếu coi như Store Manager duyệt 100% đề xuất. Nếu chỉ duyệt 60%, phần lợi nhuận tăng thêm còn khoảng 60%: lợi ích phụ thuộc vào việc người dùng thực sự làm theo.
4. Chỉ có 3 chuỗi nhu cầu trên một giai đoạn 60 ngày, không đủ để nói về độ tin cậy thống kê.
5. Khi khách không mua theo FEFO, cả A và B đều hủy nhiều hơn một chút nên chênh lệch gần như không đổi. Bộ giả lập chưa mô phỏng hao hụt (mất mát không ghi sổ).

## 6. Tham khảo cách làm của các chuỗi

- **7-Eleven Nhật:** quản lý từng mặt hàng (tanpin kanri). Nhân viên đặt hàng theo giả thuyết về thời tiết và sự kiện; hàng tươi được giao nhiều chuyến mỗi ngày; coi trọng "chance loss" (mất doanh thu do hết hàng) ngang với hàng hủy.
- **Lawson, FamilyMart:** hệ thống AI *gợi ý* số lượng đặt, nhân viên xác nhận hoặc chỉnh lại. Đây chính là mô hình HITL mà Ops Chest đi theo.
- **Bách Hóa Xanh, Circle K (Việt Nam):** giảm giá hàng tươi cuối ngày, là cơ sở cho tính năng "giờ vàng".

## 7. Ngoài phạm vi (hướng phát triển)

- Mô phỏng hao hụt trong backtest.
- Đọc hóa đơn giao hàng bằng ảnh (hiện chỉ đọc tem HSD từng dòng).
- Điều chuyển hàng giữa nhiều cửa hàng.
- Tích hợp POS/ERP thật.
- Tham số đặt hàng do Store Manager tự chỉnh (z, chu kỳ).
- Học hệ số co giãn từ lịch sử giảm giá.
