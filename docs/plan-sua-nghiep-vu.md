# Plan sửa nghiệp vụ Ops Chest

Góc nhìn: người vận hành cửa hàng tiện lợi độc lập. Lập ngày 10/11/2026, trên nhánh `fix/business-rules` (commit `db6628d`).

Lúc lập, tài liệu này chỉ là kế hoạch; mọi nhận định "hiện trạng" đọc từ code, chưa chạy test hay backtest. Trạng thái triển khai ghi ở mục 0.

## 0. Trạng thái triển khai

Mặc định đã dùng cho các câu hỏi ở mục 8 (chờ xác nhận): (1) cửa hàng có giờ đóng cửa, danh sách rút kệ chạy buổi tối; (2) chấp nhận lợi nhuận backtest giảm để hết hàng của B không cao hơn A; (3) trả NCC hỗ trợ cả hoàn tiền và đổi hàng; (4) làm đủ ba đợt, N10 làm cuối.

| ID | Trạng thái | Ghi chú |
|---|---|---|
| N1 | Xong (đợt 1) | Phiếu kiểm date mù theo HSD, `STOCK_ADJUST` cấp lô (`mode: LOT`). |
| N2 | Xong (đợt 1) | Lô `PULLED`, danh sách rút kệ sau giờ đóng cửa, `DISPOSE` đóng lô và ghi hao hụt. `pull_days_before_expiry` dùng trong báo cáo cận date, đặt hàng, tua nhanh; bộ backtest vẫn bán đến HSD. |
| N3 | Xong (đợt 1) | `StockMovement.reason`; báo hủy có lý do là đề xuất `DISPOSE` (không thêm loại mới), báo cáo tách theo lý do. |
| N4 | Xong (đợt 1) | Nhiều lô mỗi dòng, từ chối tại cửa, chuẩn 2/3 vòng đời, giao thiếu/dư, giá hóa đơn. Form nhận hàng trong chat vẫn một HSD mỗi dòng; form đầy đủ ở trang Đặt & nhận hàng. |
| N6 | Xong (đợt 2) | Sàn 95/90/50% trong config, dùng cả ở engine DB và bộ giả lập. Backtest đo thêm hết hàng của hàng kéo khách, nhóm A và "cả nhóm tươi trống". Thêm dòng "B không có sàn" và "sàn nhóm A 80%". |
| N9 | Xong (đợt 2) | `max_stock_qty`, `min_display_qty`; demo: tủ kem 36 đơn vị, hàng bền trưng bày tối thiểu 2–3. |
| N7 | Xong (đợt 2) | `delivery_weekdays`, bảng `supplier_closures`; demo seed lịch nghỉ Tết cho 8 đại lý. Baseline A trong backtest không tính trước kỳ nghỉ (giống cửa hàng làm tay). |
| N8 | Xong (đợt 2) | Phương án bù đơn/hoãn trong payload, duyệt đơn dưới mức cần `min_order_ack`. Bộ giả lập vẫn bỏ qua đơn tối thiểu. |
| N15 | Xong (đợt 2) | Dòng SM tự thêm được áp chiết khấu của thỏa thuận. |
| N5 | Xong (đợt 3) | Bảng `supplier_returns`, lô `RETURN_PENDING` tách từ lô gốc, `return_mode` CREDIT/EXCHANGE (demo: NCC sữa đổi hàng). Xác nhận/lấy hàng/từ chối/đã nhận tiền là thao tác của SM qua REST, không qua đề xuất. Bộ backtest vẫn ghi tiền hoàn ngay (ghi trong giới hạn). |
| N13 | Xong (đợt 3) | `inventory_snapshots` (job sáng, tua nhanh, seed), hao hụt trừ vào lợi nhuận gộp, GMROI, điểm NCC, hủy theo lý do. |
| N12 | Xong (đợt 3) | `listed_date`, nhãn hàng mới, kế hoạch xả tồn trên thẻ ngừng nhập. Luồng SKU tham chiếu để ở P2. |
| N14 | Xong (đợt 3) | `last_counted_date` (ghi ở endpoint đếm, không ở builder), lịch A/B/C 7/14/30 ngày, phát hiện tồn ảo. |
| N11 | Xong (đợt 3) | Bảng `category_policies` (`markdown_allowed`, `max_markdown_pct`); chặn ở engine, sửa tay, sửa qua chat và lúc thực thi. Không ghi khẳng định pháp lý; docs ghi cần đối chiếu Nghị định 81/2018/NĐ-CP. |
| N10 | Xong (đợt 3) | Tỷ trọng theo khung giờ trong `category_policies`, giờ giảm sau khung đỉnh (cơm 14h, bánh mì 11h, nhóm khác 18h). Bộ giả lập có bảng khung giờ "thật" lệch nhẹ; thêm dòng độ nhạy "giờ giảm giá cố định 18h". |

Các mục P2 ở mục 5 được ghi vào "Ngoài phạm vi" của `docs/nghiep-vu.md`, không làm.


## 1. Kết luận ngắn

Phần **tính toán** của Ops Chest (dự báo, newsvendor, trần HSD, so sánh phương án cận date) làm tốt hơn đa số đồ án cùng loại. Chỗ yếu nằm ở **sổ sách và thao tác tại cửa hàng**: hệ thống tin rằng số trên sổ là số trên kệ, và coi mọi việc đều là "đề xuất chờ duyệt". Ngoài thực tế có ba điều khác hẳn:

1. **Sổ theo lô luôn lệch với kệ.** POS chỉ biết SKU, khách không lấy hàng theo FEFO, hàng còn bị mất và vỡ. Toàn bộ cảnh báo cận date dựa trên một con số không ai kiểm.
2. **Có việc không phải là quyết định.** Gỡ hàng hết hạn khỏi kệ là bắt buộc, không chờ Store Manager duyệt. Cái cần duyệt là bút toán ghi hủy.
3. **Tiền chỉ có khi đối tác xác nhận.** Trả hàng cho NCC được ghi tiền hoàn ngay lúc duyệt, trong khi NCC chưa trả lời và hàng còn nằm ở cửa hàng.

Nếu chỉ kịp làm một phần trước khi bảo vệ, làm **Đợt 1** và mục **N6** (xem mục 6).

## 2. Bảng tóm tắt

Mức: **P0** sai nghiệp vụ, phải sửa. **P1** thiếu so với thực tế, nên sửa. **P2** chỉ ghi vào giới hạn của đồ án.
Công sức: S dưới nửa ngày, M một đến hai ngày, L từ ba ngày.

| ID | Vấn đề | Mức | Công sức | Đợt |
|---|---|---|---|---|
| N1 | Số lượng theo lô lệch với kệ, không có bước "kiểm date" | P0 | M | 1 |
| N2 | Hàng hết hạn chờ duyệt mới rời sổ; số hủy lấy theo sổ, không theo số đếm | P0 | M | 1 |
| N3 | Không ghi hủy được hàng vỡ, hỏng, móp; hủy không có lý do | P0 | S | 1 |
| N4 | Nhận hàng: một dòng một HSD, giao thiếu/dư không ai biết, date ngắn vẫn nhận | P0 | M | 1 |
| N5 | Trả NCC ghi tiền hoàn ngay khi duyệt; không có đổi hàng | P0 | M | 3 |
| N6 | Tỷ lệ hết hàng cao hơn cả baseline; sàn mức phục vụ 30% | P0 | M | 2 |
| N7 | Không có lịch giao và lịch nghỉ của NCC (Tết) | P1 | M | 2 |
| N8 | Đơn dưới giá trị tối thiểu chỉ được cảnh báo | P1 | M | 2 |
| N9 | Không có sức chứa kệ/tủ mát và tồn trưng bày tối thiểu | P1 | S | 2 |
| N10 | Giờ giảm giá cố định 18h cho mọi nhóm hàng | P1 | L | 3 |
| N11 | Giảm giá không có ràng buộc pháp lý (trần mức giảm, nhóm cấm) | P1 | S | 3 |
| N12 | Ngừng nhập không có kế hoạch xả tồn; hàng mới bị xét ngừng nhập | P1 | M | 3 |
| N13 | KPI: tồn trung bình sai ở kỳ trước, thiếu hao hụt, thiếu chấm điểm NCC | P1 | M | 3 |
| N14 | Kiểm kê không có lịch và không phát hiện "tồn ảo" | P1 | S | 3 |
| N15 | Lỗi nhỏ: dòng SM tự thêm vào đơn không được chiết khấu | P1 | S | 2 |

## 3. P0: sai nghiệp vụ

### N1. Kiểm date: đếm theo lô, không chỉ theo SKU

**Hiện trạng.** Kiểm kê (`services/stockcount.py`) đếm theo SKU. Thiếu thì trừ lô gần hết hạn trước, dư thì cộng vào lô mới nhất (`proposals/executor.py`, `_stock_adjust`). Doanh số POS cũng trừ lô theo FEFO giả định.

**Vì sao sai.** Khách hay với tay lấy hộp sữa ở phía trong, tức lô mới. Sổ ghi lô cũ đã hết, trên kệ lô cũ vẫn còn. Hệ quả: lô sắp hết hạn không hiện trong báo cáo cận date, không được đề xuất giảm giá, và quá hạn ngay trên kệ mà sổ không biết. Bảng độ nhạy đã có dòng "20–50% lượt mua lấy lô mới", nhưng chỉ đo lượng hủy; nó không cho hệ thống cách nào sửa sổ.

**Sửa.**

- Thêm phiếu **Kiểm date**: liệt kê SKU có lô còn ≤ N ngày (FRESH mỗi ngày, SHORT mỗi tuần, LONG mỗi tháng). Với mỗi SKU, nhân viên nhập số lượng thực **theo từng HSD nhìn thấy trên kệ**. Phiếu hiện các HSD sổ đang có, không hiện số lượng (giữ nguyên tắc đếm mù), và cho thêm HSD chưa có trong sổ.
- Chênh lệch tạo đề xuất `STOCK_ADJUST` ở **cấp lô**: mỗi item có `lot_id` hoặc `expiry_date`, không còn quy tắc "trừ lô cũ trước".
- Kiểm kê theo SKU giữ nguyên cho hàng LONG còn xa hạn.

**Chạm vào.** `services/stockcount.py`, `proposals/builders.py` (`stock_adjust`), `proposals/executor.py` (`_stock_adjust`), `api/routes_store.py`, `frontend/src/pages/StockCount.tsx`.

**Xong khi.** Test: sổ có lô A (hạn mai) 0, lô B 10; đếm thấy A 3, B 7 → sau duyệt sổ đúng A 3, B 7, tổng không đổi, lô A xuất hiện trong báo cáo cận date.

### N2. Hàng hết hạn: gỡ kệ ngay, duyệt sau

**Hiện trạng.** Lô quá hạn vẫn `ACTIVE` cho đến khi SM duyệt `DISPOSE`, và job chỉ tạo đề xuất vào sáng hôm sau (`jobs/daily.py`). Số lượng hủy lấy từ sổ. Sửa số thì chỉ giảm được (`min(q, lot.qty_remaining)`), phần còn lại tiếp tục nằm trên sổ như hàng quá hạn và bị đề xuất lại mãi.

**Vì sao sai.** Bán hàng quá hạn là vi phạm an toàn thực phẩm, nên gỡ kệ là việc bắt buộc của ca làm, không phải quyết định chờ duyệt. Nguyên tắc "mọi quyết định cuối là của Store Manager" vẫn giữ được: SM quyết bút toán ghi hủy, không quyết việc có gỡ hay không. Thêm nữa, số thực gỡ ra hiếm khi bằng số sổ (xem N1).

**Sửa.**

- **Danh sách rút kệ** cuối ngày cho các lô hết hạn hôm nay. Nhân viên xác nhận **số thực gỡ**. Xác nhận xong lô chuyển sang `PULLED`: không còn là tồn bán được, không cần duyệt.
- Đề xuất `DISPOSE` cho SM dùng số thực gỡ. Phần chênh với sổ ghi thành `ADJUST` (hao hụt), lô đóng hẳn.
- Thêm `Product.pull_days_before_expiry` (gợi ý FRESH 0, SHORT 1, LONG 7). "Ngày bán cuối" = HSD − số ngày này; engine cận date và trần HSD dùng ngày bán cuối. Phần này có thể tách ra làm sau.

**Chạm vào.** `models/inventory.py` (trạng thái lô), `proposals/builders.py` (`dispose_expired`), `proposals/executor.py` (`_dispose`), `services/briefing.py`, `jobs/daily.py` (`run_evening`), `frontend/src/pages/Expiring.tsx`.

**Xong khi.** Sau bước rút kệ, không lô quá hạn nào còn tính vào tồn hay vào đơn đặt hàng, kể cả khi SM chưa duyệt. Sổ còn 5, gỡ thực 3 → WASTE 3, ADJUST −2, lô đóng.

### N3. Hủy hàng không vì hết hạn, kèm mã lý do

**Hiện trạng.** `dispose_expired` chỉ lấy lô có HSD < hôm nay. Ghi chú luôn là "Hủy hàng quá hạn". Hàng vỡ, móp, hỏng do tủ mát chỉ có thể xử lý gián tiếp qua kiểm kê.

**Sửa.** Thêm `StockMovement.reason` với các giá trị `EXPIRED`, `DAMAGED`, `SPOILED`, `SUPPLIER_DEFECT`, `OTHER`. Nhân viên báo hủy theo lô kèm lý do (form hoặc chat), SM duyệt. Báo cáo chi phí tách hủy theo lý do: tủ mát hỏng và đặt dư là hai vấn đề khác nhau, cách xử lý cũng khác.

**Chạm vào.** `models/inventory.py`, migration, `proposals/builders.py`, `agent/tools.py`, `services/reports.py`.

### N4. Nhận hàng

**Hiện trạng** (`services/receiving.py`).

- Một dòng PO thành đúng một lô với một HSD.
- `received_qty` nhận bất kỳ số không âm nào. Giao dư không bị chặn. Giao thiếu thì đơn vẫn chuyển `RECEIVED` và không ai được báo.
- Giá vốn của lô lấy theo PO, không theo hóa đơn giao hàng.
- Hàng đã qua nửa vòng đời chỉ ghi một dòng audit, vẫn nhận.
- Không nhận được hàng ngoài đơn.

**Vì sao sai.** Một thùng giao tới thường trộn hai ba HSD. Giao thiếu và đổi giá là chuyện hằng tuần với đại lý. Từ chối hàng date ngắn tại cửa là công cụ giảm hủy rẻ nhất mà cửa hàng có, vì sau khi đã ký nhận thì rủi ro thuộc về cửa hàng.

**Sửa.**

- Mỗi dòng nhận nhiều cặp (số lượng, HSD), mỗi cặp thành một lô.
- Thêm `rejected_qty` và lý do (móp, date ngắn, sai hàng).
- Chuẩn nhận hàng `min_remaining_life_pct` (gợi ý 2/3 vòng đời). Dưới ngưỡng thì mặc định từ chối; muốn nhận phải có SM xác nhận.
- Giao thiếu: lưu phần thiếu, đưa vào bản tin và điểm NCC (N13). Không tạo đơn bù; lần đặt sau tự tính lại.
- Giao dư quá 10% hoặc quá một quy cách: cần SM xác nhận.
- Nhập `actual_unit_cost` khi hóa đơn khác PO; lô dùng giá thực và hệ thống cảnh báo chênh lệch.

**Chạm vào.** `services/receiving.py`, `models/ops.py` (`POLine`), migration, `api/routes_core.py`, `frontend/src/pages/Orders.tsx`, `tests/test_receive_form.py`.

**Xong khi.** Một dòng 24 chai nhận thành hai lô 12 + 12 với hai HSD. Giao thiếu hiện trong bản tin. Lô date ngắn bị chặn nếu nhân viên nhận mà không có SM.

### N5. Trả NCC: vòng đời và đổi hàng

**Hiện trạng** (`_return` trong `proposals/executor.py`). Khi SM duyệt, hệ thống trừ tồn, ghi `RETURN` với tiền hoàn, gửi email, tất cả trong một bước. Lợi nhuận gộp cộng khoản tiền này ngay.

**Vì sao sai.** NCC có thể từ chối, nhận một phần, hoặc hai tuần sau mới ghé lấy. Trong lúc đó hàng vẫn ở cửa hàng. Với đại lý ở Việt Nam, hình thức phổ biến là **đổi date** (đổi hàng mới một-một) hoặc trừ vào đơn sau, ít khi hoàn tiền. Ghi tiền trước khi NCC xác nhận làm đẹp KPI bằng tiền chưa có.

**Sửa.**

- Bảng `supplier_returns` với trạng thái `REQUESTED → CONFIRMED → PICKED_UP → CREDITED`, và nhánh `REFUSED`.
- Duyệt đề xuất: lô chuyển sang "chờ trả" (không bán, không tính tồn), gửi email. **Chưa ghi tiền.**
- SM bấm "NCC đã lấy hàng" và nhập số thực nhận. Lúc này mới ghi `RETURN`.
- NCC từ chối: lô quay lại bán, hệ thống xét lại phương án giảm giá.
- `SupplierAgreement.return_mode`: `CREDIT` hoặc `EXCHANGE`. Với `EXCHANGE`, ghi lô mới nhập giá vốn 0 thay cho tiền hoàn.
- Bản tin nhắc phiếu trả quá hạn mà NCC chưa lấy.

**Chạm vào.** `models/ops.py`, migration, `proposals/executor.py`, `services/briefing.py`, `engines/kpi.py`, `services/reports.py`, `notify/templates/return_email.html`, `frontend/src/pages/Orders.tsx`.

**Xong khi.** Lợi nhuận gộp không đổi tại thời điểm duyệt, chỉ đổi khi xác nhận NCC đã lấy hàng. Test từ chối: lô trở lại `ACTIVE`.

### N6. Mức phục vụ và tỷ lệ hết hàng

**Hiện trạng.** Backtest ghi Ops Chest hết hàng 7,3% so với 5,6% của cách làm kinh nghiệm, ở mọi kịch bản (`docs/nghiep-vu.md` mục 5). `newsvendor_service_level` kẹp trong 0,30–0,98. Ô C-Z của hàng bền dùng z = 0,84, tức khoảng 80%.

**Vì sao sai.** Khách vào cửa hàng tiện lợi vì tin là có hàng. Với hàng chủ lực, các chuỗi thường đặt mục tiêu có hàng trên kệ từ khoảng 95% (con số tham khảo, cần trích nguồn nếu đưa vào báo cáo). Một hệ thống tăng lợi nhuận bằng cách để hết hàng nhiều hơn người làm tay sẽ không được chủ cửa hàng chấp nhận, và đây cũng là câu hội đồng dễ hỏi nhất. Sàn 30% nghĩa là có SKU engine chủ động để thiếu hàng 7 trên 10 ngày.

**Sửa.**

- Sàn mức phục vụ theo vai trò, khai báo ở config: hàng kéo khách ≥ 95%, nhóm A ≥ 90%, còn lại ≥ 50%.
- Thêm một dòng backtest "B có sàn mức phục vụ" và báo cáo trung thực: hết hàng giảm bao nhiêu, hủy tăng bao nhiêu, lợi nhuận còn bao nhiêu. Mục tiêu là hết hàng của B không cao hơn A.
- Báo cáo tỷ lệ hết hàng tách riêng cho hàng kéo khách và nhóm A.
- Hàng tươi thay thế được cho nhau (hết cơm gà thì khách lấy cơm sườn). Đo thêm hết hàng **cấp nhóm**: ngày mà cả nhóm trống kệ. Chỉ đo, chưa đổi cách đặt.

**Chạm vào.** `engines/replenishment.py`, `services/replenish.py`, `config.py`, `sim/policies.py`, `sim/backtest.py`, `sim/data/sensitivity.json` (tạo lại), `docs/nghiep-vu.md`.

**Rủi ro.** Con số "+12–14% lợi nhuận" nhiều khả năng giảm. Đó là kết quả đúng hơn, nên chấp nhận.

## 4. P1: thiếu so với thực tế

### N7. Lịch giao và lịch nghỉ của NCC

**Hiện trạng.** Ngày hàng về = hôm nay + lead time. `review_period` chỉ nhìn `order_weekdays`. Hệ số Tết có ở phía nhu cầu, phía cung thì không.

**Vì sao cần.** Đại lý nghỉ Tết bảy đến mười ngày, đúng lúc nhu cầu cao nhất. Đơn cuối trước Tết phải phủ cả kỳ nghỉ. Hiện engine sẽ đặt như một tuần thường rồi hết hàng giữa Tết.

**Sửa.** Thêm `Supplier.delivery_weekdays` và bảng `supplier_closures(start, end)`. Ngày hàng về và chu kỳ phủ bỏ qua ngày nghỉ, nên đơn trước kỳ nghỉ tự lớn lên trong khi trần HSD vẫn chặn. Bản tin cảnh báo: "NCC X nghỉ từ ngày…, đơn cuối là ngày…".

**Chạm vào.** `models/catalog.py`, `engines/replenishment.py` (`review_period`, `compute_order`), `services/replenish.py`, `proposals/executor.py` (`expected_date`), `services/briefing.py`.

### N8. Đơn dưới giá trị tối thiểu

**Hiện trạng.** `suggest_po` chỉ thêm một câu cảnh báo.

**Sửa.** Builder tính sẵn hai phương án để SM chọn:

- **Bù đơn:** kéo sớm các SKU hàng bền nhóm A/B có số ngày tồn thấp nhất cho tới khi đủ mức tối thiểu, không vượt trần HSD và sức chứa (N9).
- **Hoãn:** nếu mô phỏng cho thấy không SKU nào hết hàng trước lần giao kế tiếp.

Duyệt đơn dưới mức tối thiểu cần tick "đã thỏa thuận với NCC".

### N9. Sức chứa và tồn trưng bày tối thiểu

**Hiện trạng.** `Product` không có trường nào về không gian. Engine có thể đề xuất 5 thùng kem cho một tủ đông chứa được 2 thùng.

**Sửa.** Thêm `Product.max_stock_qty` và `Product.min_display_qty`. Order-up-to bị chặn trần theo `max_stock_qty`. Hàng bền không để tồn mục tiêu dưới `min_display_qty`, vì kệ trống một nửa bán kém hơn kệ đầy. Thẻ đề xuất ghi rõ khi một dòng bị chặn vì sức chứa.

### N10. Giờ giảm giá theo nhóm hàng

**Hiện trạng.** Giờ vàng cố định sau 18h, giả định 30% lượt khách cho mọi nhóm (`EVENING_SHARE` trong `engines/disposition.py`). Dữ liệu bán chỉ có theo ngày.

**Vì sao cần.** Cơm hộp bán chủ yếu buổi trưa. Giảm giá sau 18h ở cửa hàng khu văn phòng là giảm cho không ai mua. Bánh mì thì đỉnh buổi sáng.

**Sửa.** Bảng tỷ trọng bán theo khung giờ cho từng nhóm (sáng, trưa, chiều, tối): demo thì seed, có POS thật thì học. Giờ giảm giá đặt sau khung đỉnh của nhóm. `EVENING_SHARE` thay bằng "tỷ trọng nhu cầu còn lại sau giờ giảm". Bộ giả lập (`sim/world.py`, `sim/store_sim.py`) phải đổi cùng lúc và tạo lại bảng độ nhạy.

Mục này tốn công nhất trong P1. Nếu không kịp, ghi vào giới hạn của đồ án.

### N11. Ràng buộc pháp lý khi giảm giá

**Hiện trạng.** Mức giảm được chấp nhận tới 95% cho mọi nhóm hàng.

**Sửa.** Thêm cấu hình theo nhóm: `markdown_allowed` và `max_markdown_pct`. Theo trí nhớ của tôi, Nghị định 81/2018/NĐ-CP đặt trần giảm giá 50%, có ngoại lệ cho thực phẩm tươi sống, và cấm khuyến mại thuốc lá, rượu từ 15 độ, sữa thay thế sữa mẹ. **Phải đối chiếu lại văn bản trước khi viết vào báo cáo.** Danh mục demo chưa có các nhóm cấm, nên việc cần làm chỉ là cờ, trần, và test chặn.

### N12. Ngừng nhập và hàng mới

**Hiện trạng.**

- `_delist` chỉ đổi trạng thái sang `DELISTED`. PO đang mở vẫn giao. Tồn "bán đến hết" không có kế hoạch.
- `Product` không có ngày bắt đầu bán. SKU mới có ít lịch sử sẽ rơi vào ô C-Z; nếu lãi sau hủy ≤ 0 thì thành ứng viên ngừng nhập ngay trong những tuần đầu.
- Không có luồng thêm hàng mới. SKU chưa có lịch sử có dự báo bằng 0 nên không bao giờ được đặt.

**Sửa.**

- `Product.listed_date`. SKU dưới 8 tuần không bị xét ngừng nhập và hiện nhãn "hàng mới" thay cho ô ABC-XYZ.
- Thẻ đề xuất ngừng nhập hiện tồn còn lại, PO đang mở, số ngày dự kiến bán hết. Nếu không bán kịp trước HSD thì kèm gợi ý xả hàng.
- Luồng thêm hàng mới với "SKU tham chiếu" để mượn dự báo bốn tuần đầu: để ở P2.

### N13. KPI

**Hiện trạng và cách sửa.**

- **Tồn trung bình.** `cost_report` dùng tồn hiện tại. `kpi_compare` gọi hàm này cho cả kỳ này và kỳ trước, nên "số ngày tồn kỳ trước" được tính từ tồn hôm nay. Sửa: job hằng ngày lưu `inventory_snapshots(date, value)`, tồn trung bình lấy từ đó.
- **Hao hụt.** Đang báo riêng, chưa trừ vào lợi nhuận gộp. Sửa: trừ vào, và hiện thành một dòng riêng.
- **GMROI** = lợi nhuận gộp / tồn trung bình theo giá vốn. Đây là chỉ số chủ cửa hàng nhỏ quan tâm nhất vì vốn nằm trong hàng.
- **Điểm NCC.** Tỷ lệ giao đủ, tỷ lệ đúng hẹn, số lần giao date ngắn. Dữ liệu có sẵn sau N4.
- **Hủy theo lý do.** Có sau N3.

### N14. Lịch kiểm kê và tồn ảo

**Hiện trạng.** Kiểm kê là thao tác tự phát theo nhóm hàng, không có lịch.

**Sửa.** Lịch đếm theo ABC (A mỗi tuần, B hai tuần, C mỗi tháng), hiện trong bản tin. Thêm quy tắc phát hiện **tồn ảo**: SKU bán đều mà nhiều ngày liền doanh số bằng 0 trong khi sổ còn tồn thì đưa vào phiếu đếm. Trường hợp này kệ đã trống mà sổ chưa biết. Dự báo sẽ giảm dần và SKU không được đặt lại. Lưu ý thêm: cờ hết hàng trong `DailySales` hiện lấy từ nhu cầu hụt mà chỉ bộ giả lập biết (`sim/advance.py`, `stockout = lost > 0`). Cửa hàng thật chỉ suy được cờ này từ sổ tồn bằng 0, nên khi sổ sai thì bước hiệu chỉnh nhu cầu bị chặn cũng không chạy.

### N15. Lỗi nhỏ

Trong `apply_edits` (`proposals/service.py`), dòng hàng SM tự thêm vào đơn dùng `prod.unit_cost`, không áp chiết khấu của thỏa thuận như các dòng do engine tạo. Sửa cho thống nhất và thêm test.

## 5. P2: không làm, ghi vào giới hạn của đồ án

- **Kênh đặt hàng.** Cửa hàng độc lập phần lớn đặt qua Zalo, điện thoại, hoặc nhân viên bán hàng của nhà phân phối ghé theo tuyến. PO qua email kèm PDF là giả định của demo. Nên nói rõ khi bảo vệ.
- **Công nợ và ngân sách nhập hàng.** Cửa hàng nhỏ bị giới hạn bởi tiền mặt nhiều hơn bởi dự báo.
- **Nhiều NCC cho một SKU**, giá vốn thay đổi theo thời gian, VAT.
- **Hàng ký gửi**: NCC chịu rủi ro hủy, cách đặt hàng khác hẳn.
- **Khuyến mãi của NCC** (mua 10 tặng 1) và tác động lên nhu cầu.
- **Lịch lễ ngoài Tết** (30/4, 2/9, Trung thu). Hiện dựa vào giả thuyết SM nhập tay, chấp nhận được.
- **Đặt hàng theo nhóm có thay thế** cho hàng tươi.
- **Ước tính hết hàng cho cửa hàng thật** từ dự báo. Mục 4 của `docs/nghiep-vu.md` đã nêu.

## 6. Thứ tự thực hiện

**Đợt 1: sổ tồn đúng và an toàn thực phẩm.** N3 → N2 → N1 → N4.
Một migration `0003` cho trạng thái lô, lý do hủy, các trường nhận hàng. Làm trước vì mọi engine đều đọc sổ lô; sổ sai thì các đợt sau tối ưu trên số sai.

**Đợt 2: đặt hàng.** N6 → N9 → N7 → N8 → N15.
Tạo lại `sensitivity.json` một lần ở cuối đợt, cập nhật bảng trong `docs/nghiep-vu.md`.

**Đợt 3: tiền và báo cáo.** N5 → N13 → N12 → N14 → N11 → N10.
N10 làm cuối và bỏ được.

Mỗi mục kèm test trong `backend/tests/test_zy_business_rules.py` theo đúng tiêu chí "xong khi". Mỗi đợt một commit, chạy lại toàn bộ `pytest` và bộ eval của agent, vì N2, N3, N5 thêm loại đề xuất và trạng thái mà `agent/tools.py` cùng `agent/prompts.py` phải biết.

## 7. Điều tôi không đề nghị sửa

- Engine tất định, LLM chỉ gọi tool: giữ nguyên.
- Trần HSD, nhu cầu bị chặn, tách doanh số giảm giá khỏi nhu cầu: đúng và hiếm thấy ở đồ án.
- Đếm mù, bắt buộc nhập HSD khi nhận, giả thuyết có chấm điểm: đúng cách làm thực tế.
- Không cắt hàng kéo khách: đúng.

## 8. Cần anh/chị quyết trước khi làm

1. **Cửa hàng mở 24 giờ hay có giờ đóng cửa?** Quyết định thời điểm chạy danh sách rút kệ (N2) và giờ giảm giá (N10).
2. **N6:** chấp nhận con số lợi nhuận trong báo cáo giảm để đổi lấy tỷ lệ hết hàng không tệ hơn baseline?
3. **N5:** demo theo hướng hoàn tiền, đổi hàng, hay cả hai?
4. **Phạm vi:** làm đủ ba đợt, hay Đợt 1 cộng N6 rồi ghi phần còn lại vào giới hạn?
