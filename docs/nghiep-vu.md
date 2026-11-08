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
- Sai số chuẩn (σ) tính trên mọi quan sát, có sàn Poisson (σ ≥ √mức nền).

### Số lượng đặt (`replenishment.py`)

Cả hai chế độ dưới đây đều:

- mô phỏng FEFO đến ngày hàng về, **chỉ tính phần tồn còn hạn** khi hàng mới về;
- trừ hàng đang về;
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
  - Lô hết hạn trong ngày: chỉ **giảm giá giờ vàng sau 18h cho phần còn dư** (khoảng 30% lượt khách), nên không ăn mất doanh thu giá gốc ban ngày.
  - Lô còn vài ngày: giảm giá cả lô; engine tính cả phần doanh thu giá gốc bị mất.
- **Trả nhà cung cấp:** chỉ khi thỏa thuận cho phép và lô còn ≥ N ngày trước HSD; hoàn x% giá vốn.

## 4. Định nghĩa KPI (`kpi.py`)

| KPI | Công thức |
|---|---|
| Tỷ lệ hủy | giá vốn hàng hủy / (giá vốn hàng bán + giá vốn hàng hủy) |
| Tỷ lệ hết hàng | nhu cầu hụt / (đã bán + nhu cầu hụt) |
| Lợi nhuận gộp sau hủy | doanh thu − giá vốn bán − giá vốn hủy − giá vốn hàng trả + tiền NCC hoàn |
| Số ngày tồn | tồn kho trung bình (giá vốn) / giá vốn bán trung bình mỗi ngày |
| Mức tin cậy của agent | tỷ lệ đề xuất được duyệt, tỷ lệ bị sửa, mức sửa số lượng trung bình |

Lưu ý: dữ liệu giả lập biết chính xác "nhu cầu hụt". Cửa hàng thật không biết số này, nên phải ước tính từ dự báo trong những ngày hết hàng.

## 5. Kết quả mô phỏng A/B (`python -m app.sim.backtest`)

Hai chính sách chạy trên cùng cửa hàng, với **cùng nhu cầu khách** (tất định theo seed):

- **A, "kinh nghiệm":** mức tồn = trung bình doanh số 4 tuần × hệ số an toàn. Không biết thứ trong tuần, Tết, hay việc doanh số bị chặn khi hết hàng; không xử lý hàng cận date.
- **B, Ops Chest:** coi như Store Manager duyệt mọi đề xuất.

| Giai đoạn | Lợi nhuận gộp | Tỷ lệ hủy | Tỷ lệ hết hàng | Tồn kho TB |
|---|---|---|---|---|
| 01/08–29/10/2026 (90 ngày) | **+24,3 triệu (+16,7%)** | 12,4% → 6,5% | 5,4% → 5,6% | +10% |
| 08/09–06/11/2026 (60 ngày) | **+16,8 triệu (+17,3%)** | 11,9% → 5,8% | 6,0% → 6,3% | +11% |

Đánh đổi: B giữ tồn hàng tươi cao hơn một chút (newsvendor có tính chi phí mất khách), nhưng hủy ít hơn hẳn nhờ dự báo theo thứ trong tuần, trần HSD và giảm giá giờ vàng.

**Giới hạn cần nói rõ khi bảo vệ:**

1. Mô hình nhu cầu và hệ số co giãn là giả định.
2. Baseline A là một heuristic hợp lý, không phải hành vi đo được của một Store Manager thật.
3. Giả lập coi như Store Manager duyệt 100% đề xuất.

## 6. Tham khảo cách làm của các chuỗi

- **7-Eleven Nhật:** quản lý từng mặt hàng (tanpin kanri). Nhân viên đặt hàng theo giả thuyết về thời tiết và sự kiện; hàng tươi được giao nhiều chuyến mỗi ngày; coi trọng "chance loss" (mất doanh thu do hết hàng) ngang với hàng hủy.
- **Lawson, FamilyMart:** hệ thống AI *gợi ý* số lượng đặt, nhân viên xác nhận hoặc chỉnh lại. Đây chính là mô hình HITL mà Ops Chest đi theo.
- **Bách Hóa Xanh, Circle K (Việt Nam):** giảm giá hàng tươi cuối ngày, là cơ sở cho tính năng "giờ vàng".

## 7. Ngoài phạm vi (hướng phát triển)

- Kiểm kê và hao hụt.
- Điều chuyển hàng giữa nhiều cửa hàng.
- Tích hợp POS/ERP thật.
- Tham số đặt hàng do Store Manager tự chỉnh (z, chu kỳ).
- Học hệ số co giãn từ lịch sử giảm giá.
- Giả lập tiến ngày để demo nhiều ngày liên tiếp.
