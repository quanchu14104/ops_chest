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
- bị **chặn theo sức chứa** kệ/tủ (`Product.max_stock_qty`): tồn lúc hàng về cộng số đặt không vượt sức chứa; thẻ đề xuất ghi nhãn "sức chứa" cho dòng bị chặn;
- có **sàn mức phục vụ** theo vai trò mặt hàng (`SERVICE_FLOOR_*` trong config): hàng kéo khách ≥ 95%, nhóm A ≥ 90%, còn lại ≥ 50%. Khách vào cửa hàng tiện lợi vì tin là có hàng; engine không được chủ động để thiếu hàng chỉ vì lãi thấp. Mức 95% cho hàng chủ lực là con số tham khảo thường gặp, cần trích nguồn nếu đưa vào báo cáo;
- tính **ngày hàng về và chu kỳ phủ theo lịch NCC**: ngày giao trong tuần (`Supplier.delivery_weekdays`) và kỳ nghỉ (`supplier_closures`, ví dụ nghỉ Tết). Chu kỳ phủ = từ lúc đơn hôm nay về đến lúc đơn kế tiếp về, nên đơn cuối trước kỳ nghỉ tự lớn lên để phủ cả kỳ nghỉ (trần HSD vẫn chặn). Ngày NCC nghỉ không đến lịch đặt; bản tin cảnh báo trước 14 ngày kèm ngày đặt đơn cuối;
- làm tròn theo quy cách đóng gói.

**Đơn dưới giá trị tối thiểu** của NCC không chỉ được cảnh báo. Engine tính sẵn hai phương án để Store Manager chọn: **bù đơn** (kéo sớm từng thùng hàng bền nhóm A/B có số ngày tồn thấp nhất, không vượt trần HSD và sức chứa) và **hoãn** (chỉ khả thi khi theo dự báo không mặt hàng nào trong đơn hết trước lần giao kế tiếp). Muốn duyệt đơn vẫn dưới mức tối thiểu thì phải đánh dấu "đã thỏa thuận với NCC"; không đánh dấu thì việc thực thi bị từ chối. Dòng Store Manager tự thêm vào đơn được áp chiết khấu của thỏa thuận như dòng do engine tạo.

**Hàng dễ hư** (HSD ≤ chu kỳ đặt + 7 ngày) dùng mô hình **newsvendor**:

```
mức phục vụ tối ưu = (giá − vốn + chi phí mất khách) / (giá − giá trị thu hồi + chi phí mất khách)
```

- *Chi phí mất khách* ("chance loss", khái niệm 7-Eleven Nhật hay nhấn mạnh) = 30% giá bán, và 100% với hàng kéo khách.
- *Giá trị thu hồi* = tiền kỳ vọng thu lại khi giảm giá giờ vàng hoặc trả nhà cung cấp.
- Kết quả bị kẹp trong 30–98% rồi nâng lên sàn mức phục vụ của mặt hàng. Trước đây sàn 30% cho phép engine để một số SKU thiếu hàng 7 trên 10 ngày.

**Hàng bền** dùng **order-up-to**, với tồn an toàn `z·σ·√(L+R)` (z không thấp hơn mức ứng với sàn mức phục vụ, và tồn an toàn không thấp hơn tồn trưng bày tối thiểu `Product.min_display_qty`, vì kệ trống một nửa bán kém hơn kệ đầy) và z theo ô ABC-XYZ:

| | X | Y | Z |
|---|---|---|---|
| **A** | 2,05 | 1,65 | 1,28 |
| **B** | 1,65 | 1,28 | 1,04 |
| **C** | 1,28 | 1,04 | 0,84 |

### Rủi ro hết hạn và xử lý cận date (`expiry.py`, `disposition.py`)

Engine mô phỏng bán FEFO theo dự báo để ra **số lượng dự kiến hủy** của từng lô, rồi so sánh **tiền thu hồi kỳ vọng** của các phương án:

- **Giữ nguyên:** phần dư bị hủy, tốn thêm chi phí xử lý khoảng 500đ/đơn vị.
- **Giảm giá 20/30/50%.** Hệ số co giãn giả định: FRESH 3,0, SHORT 2,0, LONG 1,2. Đây là giả định cần hiệu chỉnh bằng dữ liệu thật.
  - Lô hết hạn trong ngày: chỉ **giảm giá giờ vàng cho phần còn dư, bắt đầu sau khung bán đỉnh của nhóm hàng**. Mỗi nhóm có bảng tỷ trọng bán theo khung giờ (sáng 6–11h, trưa 11–14h, chiều 14–17h, tối 17–22h) trong `category_policies`: cơm hộp đỉnh trưa nên giảm từ 14h, bánh mì đỉnh sáng nên giảm từ 11h, các nhóm khác giữ 18h (khoảng 30% lượt khách). Engine dùng "tỷ trọng nhu cầu còn lại sau giờ giảm" thay cho hằng số 30% cũ. Khách sau giờ giảm vốn sẽ trả giá gốc cũng được hưởng giá giảm; engine và bộ giả lập đều trừ phần này. Demo dùng bảng khai báo; khi có POS thật thì học từ giờ bán. Bộ giả lập dùng bảng khung giờ "thật" lệch nhẹ so với bảng cửa hàng khai báo, để kết quả không tự chứng minh.
  - **Ràng buộc giảm giá theo nhóm hàng** (`category_policies`): được giảm giá hay không (`markdown_allowed`) và trần mức giảm (`max_markdown_pct`, demo 50% cho mọi nhóm). Engine không đề xuất mức vượt trần; Store Manager sửa hoặc agent sửa vượt trần bị chặn; lúc thực thi kiểm tra lại. Đây là **cấu hình của cửa hàng**: trần mức giảm và danh mục hàng không được khuyến mại phải đối chiếu Nghị định 81/2018/NĐ-CP (và văn bản sửa đổi, hướng dẫn) trước khi dùng thật. Danh mục demo chưa có nhóm hàng nào cần cấm.
  - Lô còn vài ngày: giảm giá cả lô; engine tính cả phần doanh thu giá gốc bị mất.
  - Lô đang giảm giá: chỉ xét mức sâu hơn, so với phương án giữ mức hiện tại. Hệ thống không tăng giá trở lại, vì tem đã dán.
- **Trả nhà cung cấp:** chỉ khi thỏa thuận **còn hiệu lực** cho phép và lô còn ≥ N ngày trước HSD; hoàn x% giá vốn hoặc đổi hàng mới (`SupplierAgreement.return_mode`: `CREDIT` mặc định, `EXCHANGE` đổi date). Thỏa thuận hết hiệu lực thì đơn hàng không được chiết khấu và có cảnh báo.
- Một lô đang nằm trong đề xuất trả hoặc ghi hủy còn mở thì không được đề xuất lại cho đến khi đề xuất đó đóng.

### Giả thuyết của Store Manager (`services/hypotheses.py`)

Dự báo từ lịch sử không biết tuần này có trận bóng. Cách làm của 7-Eleven Nhật là để người bán đặt giả thuyết rồi kiểm chứng; đây cũng là việc chat làm tốt hơn dashboard.

- Store Manager nói trong chat, agent tạo đề xuất với **đúng hệ số và ngày người dùng nêu**. Thiếu thì agent phải hỏi, không tự chọn.
- Giới hạn bằng code: hệ số 0,3–3, tối đa 14 ngày, không trùng khoảng ngày cùng phạm vi.
- Dự báo chỉ đổi sau khi duyệt. Những ngày có sự kiện không được dùng để ước lượng mức nền, giống cách xử lý Tết.
- Hết khoảng ngày, hệ thống so lượng bán thực tế với dự báo nền đã lưu. **Đúng** nếu nhu cầu đi được ≥50% quãng đường dự đoán, **sai** nếu ≤25%, còn lại là đúng một phần. Dùng lượng bán vì cửa hàng thật không biết nhu cầu bị hụt. Khi từ 20% số SKU-ngày bị hết hàng, lượng bán chỉ là cận dưới của nhu cầu, nên hệ thống chỉ giữ kết luận mà cận dưới chứng minh được: giả thuyết tăng là "đúng", giả thuyết giảm là "sai". Các trường hợp còn lại chấm **chưa đủ căn cứ**, tránh việc nhập ít, bán ít rồi tự xác nhận là nhu cầu đã giảm.

### Học từ phần sửa (`engines/edit_learning.py`)

Chỉ gợi ý khi có ít nhất 5 lần sửa trên 3 đơn đã duyệt, trung vị lệch từ 15% và 70% số lần cùng chiều. Hệ số do code tính (làm tròn 0,05, trong khoảng 0,5–1,5), agent không chọn được. Áp dụng phải qua duyệt, tắt được bất cứ lúc nào. Hệ số tăng vẫn không vượt trần HSD.

### Ngừng nhập và hàng mới

- `Product.listed_date`: mặt hàng bán chưa đủ 8 tuần là **hàng mới**, hiện nhãn "hàng mới" thay cho ô ABC-XYZ và không bị xét ngừng nhập (ít lịch sử nên dễ rơi vào C-Z).
- Thẻ đề xuất ngừng nhập kèm **kế hoạch xả tồn**: tồn còn lại, đơn đang về, số ngày dự kiến bán hết, số đơn vị không bán kịp trước HSD. Có phần không kịp thì gợi ý xả hàng (giảm giá) và cân nhắc huỷ đơn đang về. Ngừng nhập vẫn chỉ đổi trạng thái; đơn đang mở không tự huỷ.
- Chưa có luồng thêm mặt hàng mới với "SKU tham chiếu" để mượn dự báo (xem mục 7).

### Kiểm kê theo SKU (`services/stockcount.py`)

Đếm **mù**: phiếu không hiện số trên sổ, vì người đếm thấy số sẽ có xu hướng đếm cho khớp. Nhân viên gửi số đếm; chênh lệch thành đề xuất cho Store Manager duyệt. Thiếu thì trừ lô gần hết hạn trước (không biết mất ở lô nào), dư thì cộng vào lô mới nhất. Nếu tồn đã thay đổi giữa lúc đếm và lúc duyệt, đề xuất thất bại và phải đếm lại, thay vì ghi đè bằng số cũ. Cách đếm này chỉ còn dùng cho hàng dài ngày còn xa hạn.

- **Lịch đếm theo ABC**: nhóm A mỗi tuần, B hai tuần, C mỗi tháng, tính từ lần đếm gần nhất (kiểm kê hoặc kiểm date, kể cả khi khớp sổ). Bản tin nhắc số mặt hàng đến lịch; phiếu "Đến lịch đếm" chỉ gồm các mặt hàng này.
- **Tồn ảo**: mặt hàng bán đều (trung bình ≥ 1/ngày, có bán ≥ 60% số ngày trong 4 tuần) mà 3 ngày liền không bán trong khi sổ còn hàng được đưa vào phiếu đếm, kèm lý do. Đây thường là kệ đã trống mà sổ chưa biết; để lâu thì dự báo giảm dần và mặt hàng không được đặt lại.
- Lưu ý: cờ "hết hàng" trong `DailySales` của dữ liệu demo lấy từ nhu cầu hụt mà chỉ bộ giả lập biết. Cửa hàng thật chỉ suy được cờ này từ sổ tồn bằng 0, nên khi sổ sai (tồn ảo) thì bước hiệu chỉnh nhu cầu bị chặn cũng không chạy. Phát hiện tồn ảo và kiểm date là cách giữ sổ đúng.

### Kiểm date theo lô (`services/datecheck.py`)

POS chỉ biết SKU, và khách hay với tay lấy lô mới ở phía trong kệ. Sổ ghi lô cũ đã bán hết trong khi lô cũ vẫn nằm trên kệ, nên lô sắp hết hạn không hiện trong báo cáo cận date và quá hạn ngay trên kệ mà sổ không biết.

- **Phiếu kiểm date** liệt kê các mặt hàng có lô sắp tới ngày bán cuối (hàng tươi ≤ 2 ngày, ngắn ngày ≤ 7, dài ngày ≤ 30), kèm các HSD sổ đang có nhưng **không kèm số lượng** (vẫn đếm mù). Nhân viên đếm theo từng HSD in trên bao bì và thêm được HSD mà sổ chưa có.
- Lịch: hàng tươi mỗi ngày, hàng ngắn ngày thứ Hai, hàng dài ngày ngày 1 hằng tháng; bản tin nhắc khi đến lịch.
- Mặt hàng đã nhập số thì HSD trên sổ mà phiếu để trống được tính là 0: người đếm đã xem hết kệ của mặt hàng đó.
- Chênh lệch thành đề xuất `STOCK_ADJUST` **cấp lô**. Duyệt thì sổ ghi đúng số của từng HSD; lô đã đóng trên sổ được mở lại, HSD chưa từng có thì tạo lô mới. Chuyển số giữa các lô cùng mặt hàng trong một phiếu không bị tính là hao hụt.

### Ngày bán cuối và rút kệ (`services/shelf.py`)

- Mỗi mặt hàng có `pull_days_before_expiry` (demo: tươi 0, ngắn ngày 1, dài ngày 7). **Ngày bán cuối** = HSD − số ngày này. Báo cáo cận date, đề xuất giảm giá, số lượng đặt (tồn còn bán được, trần HSD) đều tính theo ngày bán cuối; điều khoản trả NCC vẫn tính theo HSD in trên bao bì.
- Bán hàng quá hạn là vi phạm an toàn thực phẩm, nên **gỡ kệ là việc bắt buộc của ca làm, không chờ duyệt**. Cửa hàng có giờ đóng cửa (`CLOSING_HOUR`, mặc định 22h): sau giờ này có **danh sách rút kệ** cho các lô hết ngày bán. Nhân viên ghi **số thực gỡ** (phiếu không hiện số trên sổ). Xác nhận xong lô chuyển `PULLED`: không còn là tồn bán được, không tính vào đơn đặt hàng, có ghi nhật ký.
- Store Manager duyệt **bút toán ghi hủy** (`DISPOSE`) theo số thực gỡ. Phần chênh với sổ ghi `ADJUST` lý do hao hụt, lô đóng hẳn. Lô quá ngày bán cuối mà chưa ai xác nhận gỡ vẫn được đề xuất ghi hủy (theo số sổ, có cảnh báo); SM sửa số nhỏ hơn thì phần còn lại cũng ghi hao hụt, không còn nằm trên sổ để bị đề xuất lại mãi.

### Trả nhà cung cấp: vòng đời phiếu trả (`services/returns.py`)

Tiền chỉ có khi đối tác xác nhận. Phiếu trả đi qua `REQUESTED → CONFIRMED → PICKED_UP → CREDITED`, hoặc `REFUSED`.

- **Duyệt đề xuất trả hàng**: phần hàng trả được tách thành lô `RETURN_PENDING` (không bán, không tính tồn), email gửi NCC. **Chưa ghi tiền**: lợi nhuận gộp không đổi tại thời điểm duyệt.
- **NCC đã lấy hàng**: Store Manager nhập số NCC thực nhận. Lúc này mới ghi `RETURN`. Với `CREDIT` là tiền hoàn theo tỷ lệ thỏa thuận (chờ NCC trả hoặc trừ vào đơn sau, SM đánh dấu "đã nhận tiền" để đóng phiếu). Với `EXCHANGE` là lô hàng đổi giá vốn 0, HSD mới; phiếu đóng ngay. Phần NCC không nhận quay lại bán.
- **NCC từ chối**: lô quay lại bán và hệ thống xét lại phương án giảm giá (tạo đề xuất nếu có lợi).
- Bản tin nhắc phiếu đã gửi từ 5 ngày mà NCC chưa lấy hàng: trong lúc đó hàng vẫn nằm ở cửa hàng.
- Đây là thao tác của Store Manager (có nhật ký), không phải của agent; agent chỉ xem được trạng thái phiếu.

### Hủy có lý do

Mọi bút toán hủy có `reason`: `EXPIRED` (hết hạn), `DAMAGED` (vỡ, móp), `SPOILED` (hỏng do bảo quản, tủ mát), `SUPPLIER_DEFECT` (lỗi NCC), `OTHER`. Nhân viên báo hủy hàng vỡ, hỏng theo lô kèm lý do (trang Hàng cận date hoặc chat); đây là đề xuất, SM duyệt mới trừ tồn. Báo cáo chi phí tách hủy theo lý do: tủ mát hỏng và đặt dư là hai vấn đề khác nhau.

### Nhận hàng (`services/receiving.py`)

- Một dòng PO nhận được nhiều cặp (số lượng, HSD); mỗi cặp thành một lô.
- **Từ chối tại cửa** (`rejected_qty` + lý do: móp, date ngắn, sai hàng). Sau khi ký nhận, rủi ro thuộc về cửa hàng.
- **Chuẩn nhận hàng**: lô phải còn ≥ 2/3 vòng đời (`RECEIVE_MIN_REMAINING_LIFE_PCT`). Dưới chuẩn thì mặc định bị chặn; chỉ Store Manager nhận được (tick xác nhận, có ghi nhật ký).
- **Giao thiếu** được lưu theo dòng (`short_qty`), hiện trong bản tin. Không tạo đơn bù; lần đặt sau engine tự tính lại.
- **Giao dư** quá 10% hoặc quá một quy cách (lấy mức lớn hơn) cần Store Manager xác nhận.
- **Giá hóa đơn** khác PO: nhập `actual_unit_cost`, lô dùng giá thực và hệ thống cảnh báo chênh lệch.
- Chưa hỗ trợ nhận hàng ngoài đơn.

### Đọc ảnh tem HSD (`agent/vision.py`)

Model chỉ đọc chữ in trên bao bì; việc hiểu ngày (ngày trước tháng, chỉ có tháng/năm thì lấy cuối tháng) do code tất định làm. Không đọc được HSD thì trả rỗng và không bao giờ lấy NSX thay thế. Kết quả chỉ điền sẵn ô HSD, người nhận hàng vẫn phải đối chiếu và xác nhận; ảnh không được lưu. Đã thử trên ảnh tem tự tạo, **chưa thử trên ảnh bao bì thật**.

## 4. Định nghĩa KPI (`kpi.py`)

| KPI | Công thức |
|---|---|
| Tỷ lệ hủy | giá vốn hàng hủy / (giá vốn hàng bán + giá vốn hàng hủy) |
| Tỷ lệ hết hàng | nhu cầu hụt / (đã bán + nhu cầu hụt) |
| Lợi nhuận gộp sau hủy | doanh thu − giá vốn bán − giá vốn hủy − giá vốn hàng trả + tiền NCC hoàn − hao hụt. Hàng trả và tiền hoàn chỉ tính khi NCC đã lấy hàng |
| Số ngày tồn | tồn kho trung bình (giá vốn) / giá vốn bán trung bình mỗi ngày. Tồn trung bình lấy từ **ảnh chụp tồn cuối ngày** (`inventory_snapshots`) trong đúng kỳ, nên kỳ trước không còn dùng tồn hôm nay |
| GMROI | lợi nhuận gộp / tồn kho trung bình theo giá vốn, trong kỳ: mỗi đồng vốn nằm trong hàng sinh ra bao nhiêu lãi gộp |
| Điểm NCC | trên các đơn đến hạn giao trong kỳ: tỷ lệ giao đủ, tỷ lệ đúng hẹn, số lần giao date ngắn, số đơn vị bị từ chối tại cửa |
| Mức tin cậy của agent | tỷ lệ đề xuất được duyệt, tỷ lệ bị sửa, mức sửa số lượng trung bình |
| Hao hụt | điều chỉnh âm ròng theo từng (mặt hàng, phiếu), gồm kiểm kê, kiểm date và chênh lệch khi rút kệ; chuyển số giữa các lô cùng phiếu không tính. Hiện thành dòng riêng và trừ vào lợi nhuận gộp |
| Hủy theo lý do | giá vốn hủy tách theo `EXPIRED` / `DAMAGED` / `SPOILED` / `SUPPLIER_DEFECT` / `OTHER` |

Lưu ý: dữ liệu giả lập biết chính xác "nhu cầu hụt". Cửa hàng thật không biết số này, nên phải ước tính từ dự báo trong những ngày hết hàng.

## 5. Kết quả mô phỏng A/B (`python -m app.sim.backtest`)

Hai chính sách chạy trên cùng cửa hàng, với **cùng nhu cầu khách** (tất định theo seed):

- **A, "kinh nghiệm":** mức tồn = trung bình doanh số 4 tuần × hệ số an toàn; cuối ngày giảm 30% hàng hết hạn hôm nay. Không biết thứ trong tuần, Tết, hay việc doanh số bị chặn khi hết hàng.
- **B, Ops Chest:** coi như Store Manager duyệt mọi đề xuất.

**Thiết kế để kết quả không tự chứng minh:** hệ số co giãn của "thế giới giả lập" (`sim/world.py`) tách khỏi hệ số engine giả định. Ở kịch bản tham chiếu, khách chỉ phản ứng với giảm giá bằng 50% mức engine tin (FRESH 1,5 so với 3,0), nghĩa là engine cố tình bị sai mô hình. Chính sách B chỉ dùng thứ cửa hàng quan sát được.

Bảng dưới (08/09–06/11/2026, 60 ngày). Mỗi dòng chỉ đổi một điều so với dòng tham chiếu. Tạo lại bằng `python -m app.sim.backtest --sensitivity`, và cũng hiện trong trang **Phân tích**. Hai cột cuối là tỷ lệ hết hàng riêng của hàng kéo khách và nhóm A (nhóm A xếp theo lợi nhuận 90 ngày trước kỳ so sánh, cùng một tập SKU cho cả A và B).

| Kịch bản | Lợi nhuận B so với A | Tỷ lệ hủy A / B | Hết hàng A / B | Hàng kéo khách A / B | Nhóm A: A / B |
|---|---|---|---|---|---|
| **Tham chiếu** | **+4,2%** | 11,1% / 9,8% | 6,1% / 4,6% | 4,1% / 2,3% | 4,8% / 2,6% |
| B không có sàn mức phục vụ (cách đặt cũ) | +12,8% | 11,1% / 6,3% | 6,1% / 7,4% | 4,1% / 5,0% | 4,8% / 6,3% |
| Giờ giảm giá cố định 18h cho mọi nhóm (cách cũ) | +1,9% | 11,1% / 11,1% | 6,1% / 4,7% | 4,1% / 2,4% | 4,8% / 2,7% |
| Sàn nhóm A 80% thay vì 90% | +6,7% | 11,1% / 9,0% | 6,1% / 5,3% | 4,1% / 2,3% | 4,8% / 3,6% |
| Nhu cầu khác (seed 11) | +2,7% | 11,7% / 10,6% | 5,9% / 4,8% | 3,8% / 1,9% | 4,5% / 2,4% |
| Nhu cầu khác (seed 23) | +4,9% | 11,2% / 9,7% | 6,1% / 4,5% | 2,5% / 1,1% | 4,4% / 2,0% |
| Khách phản ứng đúng 100% giả định | +8,7% | 11,0% / 8,6% | 5,9% / 4,3% | 3,6% / 2,3% | 4,6% / 2,4% |
| Khách chỉ phản ứng 25% giả định | +1,8% | 11,5% / 10,8% | 6,2% / 4,7% | 4,4% / 2,4% | 4,9% / 2,7% |
| B chỉ đặt hàng (tắt giảm giá, trả NCC) | +0,2% | 11,1% / 12,2% | 6,1% / 4,7% | 4,1% / 2,4% | 4,8% / 2,7% |
| B không tách doanh số giảm giá khỏi nhu cầu | +1,0% | 11,1% / 10,8% | 6,1% / 4,2% | 4,1% / 1,9% | 4,8% / 2,4% |
| Store Manager chỉ duyệt 80% đề xuất | +3,3% | 11,1% / 10,4% | 6,1% / 4,8% | 4,1% / 2,7% | 4,8% / 3,0% |
| Store Manager chỉ duyệt 60% đề xuất | +1,2% | 11,1% / 11,1% | 6,1% / 5,0% | 4,1% / 3,4% | 4,8% / 3,5% |
| 20% lượt mua lấy lô mới (không theo FEFO) | +3,4% | 11,2% / 10,1% | 6,1% / 4,6% | 4,1% / 2,3% | 4,8% / 2,6% |
| 50% lượt mua lấy lô mới (không theo FEFO) | +2,3% | 11,4% / 10,5% | 6,1% / 4,7% | 4,1% / 2,3% | 4,9% / 2,7% |
| Cách so sánh cũ (A không giảm giá, khách phản ứng đúng giả định) | +10,5% | 11,8% / 8,6% | 6,2% / 4,3% | 4,5% / 2,3% | 5,0% / 2,4% |

**Đổi so với bản trước.** Bản trước (commit `db6628d`) ghi tham chiếu +13,6% lợi nhuận, hủy 11,0% / 6,5%, hết hàng 5,6% / 7,3%: B lãi hơn nhờ để thiếu hàng nhiều hơn người làm tay. Ba thay đổi làm số đổi:

1. **Sàn mức phục vụ (N6):** hàng kéo khách 95%, nhóm A 90%, còn lại 50%. Ở tham chiếu B hết hàng 4,6% so với 6,1% của A (hàng kéo khách 2,3% so với 4,1%, nhóm A 2,6% so với 4,8%); B không hết hàng nhiều hơn A ở mọi dòng trừ dòng cố ý tắt sàn. Dòng "B không có sàn mức phục vụ" tái hiện cách đặt cũ: +12,8% lợi nhuận nhưng hết hàng 7,4% so với 6,1%.
2. **Giờ giảm giá theo khung bán (N10):** thế giới giả lập giờ có khung giờ bán theo nhóm hàng (cơm hộp bán chủ yếu buổi trưa, bánh mì buổi sáng). Giờ vàng cố định 18h vì thế kém tác dụng với hàng tươi, cho cả A (luôn giảm lúc 18h) và B. Dòng "giờ giảm giá cố định 18h" cho thấy riêng việc đặt giờ giảm theo nhóm đóng góp khoảng 2 điểm lợi nhuận (+4,2% so với +1,9%) và hạ tỷ lệ hủy của B từ 11,1% xuống 9,8%.
3. **Lịch nghỉ Tết của đại lý (N7):** giai đoạn khởi động 200 ngày nay đi qua Tết 2026 với lịch nghỉ, nên trạng thái kho lúc bắt đầu so sánh khác trước; số của A cũng đổi nhẹ.

Con số nên trích dẫn là **lợi nhuận gộp khoảng +3–5% (tham chiếu +4,2%; hai chuỗi nhu cầu khác +2,7% và +4,9%), hết hàng thấp hơn baseline (4,6% so với 6,1%), tỷ lệ hủy thấp hơn khoảng 1,3 điểm**. Lợi ích nhỏ hơn hẳn bản trước, đúng như rủi ro đã nêu trong plan; đây là kết quả trung thực hơn vì B không còn "mua" lợi nhuận bằng cách để kệ trống.

Dòng "sàn nhóm A 80%" cho thấy sàn là một nút chỉnh chứ không phải hằng số: hạ sàn thì lợi nhuận +6,7% và hết hàng 5,3%, vẫn dưới A. Mức sàn là chính sách của cửa hàng, nên giữ mức trong plan thay vì chọn mức cho số đẹp nhất trên bảng này.

**Điểm cần nói thẳng:**

- Ở dòng "B chỉ đặt hàng", B hủy **nhiều hơn** A (12,2% so với 11,1%) và lợi nhuận gần như hòa (+0,2%): với sàn mức phục vụ, phần đặt hàng một mình đổi hủy lấy có hàng; giảm giá cận date và trả NCC mới kéo tỷ lệ hủy xuống dưới A.
- Khi Store Manager chỉ duyệt 60% đề xuất, lợi ích gần như hết (+1,2%). Khi khách phản ứng với giảm giá chỉ bằng 25% giả định, còn +1,8%.
- Hết hàng "cả nhóm hàng tươi trống" (ngày mà mọi món trong nhóm đều hết) được đo nhưng không xảy ra trong mô phỏng ở cả A và B, vì mỗi nhóm có 6–20 món.

**Giới hạn cần nói rõ khi bảo vệ:**

1. Mô hình nhu cầu và hệ số co giãn đều là giả định; bảng độ nhạy chỉ cho biết kết luận chịu được sai lệch tới đâu.
2. Baseline A là một heuristic hợp lý, không phải hành vi đo được của một Store Manager thật.
3. Kịch bản tham chiếu coi như Store Manager duyệt 100% đề xuất. Nếu chỉ duyệt 60%, phần lợi nhuận tăng thêm gần như mất hết: lợi ích phụ thuộc vào việc người dùng thực sự làm theo.
4. Chỉ có 3 chuỗi nhu cầu trên một giai đoạn 60 ngày, không đủ để nói về độ tin cậy thống kê.
5. Khi khách không mua theo FEFO, cả A và B đều hủy nhiều hơn một chút nên chênh lệch gần như không đổi. Bộ giả lập chưa mô phỏng hao hụt (mất mát không ghi sổ).
6. Bộ giả lập bán đến HSD (chưa dùng ngày bán cuối), bỏ qua giá trị đơn tối thiểu và ghi tiền NCC hoàn ngay khi trả; engine trong ứng dụng thì có các quy tắc này. Bảng khung giờ bán của "thế giới" do chúng tôi đặt, không đo từ POS thật.

## 6. Tham khảo cách làm của các chuỗi

- **7-Eleven Nhật:** quản lý từng mặt hàng (tanpin kanri). Nhân viên đặt hàng theo giả thuyết về thời tiết và sự kiện; hàng tươi được giao nhiều chuyến mỗi ngày; coi trọng "chance loss" (mất doanh thu do hết hàng) ngang với hàng hủy.
- **Lawson, FamilyMart:** hệ thống AI *gợi ý* số lượng đặt, nhân viên xác nhận hoặc chỉnh lại. Đây chính là mô hình HITL mà Ops Chest đi theo.
- **Bách Hóa Xanh, Circle K (Việt Nam):** giảm giá hàng tươi cuối ngày, là cơ sở cho tính năng "giờ vàng".

## 7. Ngoài phạm vi (hướng phát triển)

- Mô phỏng hao hụt trong backtest.
- **Kênh đặt hàng.** Cửa hàng độc lập phần lớn đặt qua Zalo, điện thoại, hoặc nhân viên bán hàng của nhà phân phối ghé theo tuyến. Gửi đơn qua email kèm PDF là giả định của demo.
- **Công nợ và ngân sách nhập hàng.** Cửa hàng nhỏ bị giới hạn bởi tiền mặt nhiều hơn bởi dự báo; engine chưa có ràng buộc ngân sách.
- **Nhiều NCC cho một SKU**, giá vốn thay đổi theo thời gian, VAT.
- **Hàng ký gửi**: NCC chịu rủi ro hủy, cách đặt hàng khác hẳn.
- **Khuyến mãi của NCC** (mua 10 tặng 1) và tác động lên nhu cầu.
- **Lịch lễ ngoài Tết** (30/4, 2/9, Trung thu): hiện dựa vào giả thuyết Store Manager nhập tay.
- **Đặt hàng theo nhóm có thay thế** cho hàng tươi (hết cơm gà thì khách lấy cơm sườn). Hiện chỉ đo hết hàng cấp nhóm, chưa đổi cách đặt.
- **Ước tính hết hàng cho cửa hàng thật** từ dự báo (xem lưu ý ở mục 4).
- **Luồng thêm mặt hàng mới** với "SKU tham chiếu" để mượn dự báo bốn tuần đầu; SKU chưa có lịch sử hiện có dự báo bằng 0 nên không được đề xuất đặt.
- **Nhận hàng ngoài đơn** và đọc hóa đơn giao hàng.
- Đọc hóa đơn giao hàng bằng ảnh (hiện chỉ đọc tem HSD từng dòng).
- Điều chuyển hàng giữa nhiều cửa hàng.
- Tích hợp POS/ERP thật.
- Tham số đặt hàng do Store Manager tự chỉnh (z, chu kỳ).
- Học hệ số co giãn từ lịch sử giảm giá.
