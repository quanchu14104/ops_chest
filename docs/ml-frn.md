# Dự báo bằng LightGBM trên FreshRetailNet-50K

Tài liệu này mô tả vì sao và bằng cách nào Ops Chest (OC) chuyển từ **nhu cầu giả lập** sang **nhu cầu thật** của bộ dữ liệu FreshRetailNet-50K (FRN), và dùng mô hình **LightGBM** thay engine dự báo EWMA cho hàng tươi. Các con số trong mục "Kết quả" lấy từ `backend/app/sim/data/frn/report.json` và `backtest.json`. Đó là đầu ra của một lần chạy trên Kaggle; chạy lại có thể lệch nhẹ.

## 1. Vì sao đổi

Trước đây mọi kết quả của OC đều đo trên cửa hàng giả lập do nhóm tự dựng. Dự báo, độ co giãn khi giảm giá và khung giờ bán đều là giả định, nên kết quả dễ bị hỏi "có phải tự chứng minh không". FRN cho phép:

1. **học và kiểm chứng** dự báo trên nhu cầu thật;
2. **đo** khung giờ bán theo nhóm hàng, thay cho bảng tự đặt;
3. **thử đo** độ co giãn khi giảm giá. Kết quả: FRN không cho ước lượng đáng tin (mục 5.4);
4. chạy backtest A/B trên **nhiều điểm bán thật** thay vì 3 chuỗi nhu cầu ngẫu nhiên.

## 2. Dữ liệu

- **Nguồn:** [FreshRetailNet-50K](https://huggingface.co/datasets/Dingdong-Inc/FreshRetailNet-50K), Dingdong (Trung Quốc), giấy phép **CC BY 4.0**. Bài báo: [arXiv 2505.16319](https://arxiv.org/abs/2505.16319).
- **Quy mô:**
  - 50.000 chuỗi (điểm bán × mặt hàng), 898 điểm bán, 18 thành phố, 865 mặt hàng tươi;
  - 7 nhóm quản lý, 32 / 84 / 233 nhóm hàng cấp 1 / 2 / 3.
- **Thời gian:** 28/03–25/06/2024 (90 ngày train) và 26/06–02/07/2024 (7 ngày eval). Có số bán theo ngày và theo giờ.
- **Đã kiểm trên dữ liệu** (`ml/kaggle/explore_frn.py`):
  - `hours_stock_status` = 1 là **hết hàng**, ngược với cách bài báo mô tả. Tổng các giờ hết hàng từ 6h đến 22h khớp tuyệt đối với `stock_hour6_22_cnt`.
  - **44% ngày–chuỗi có ít nhất một giờ hết hàng**; 4% hết hàng cả 16 giờ.
  - `sale_amount` đã được **quy đổi** (trung bình khoảng 1,0 mỗi ngày), không phải số đơn vị thật. Tổng 24 giờ đúng bằng số bán trong ngày.
  - `discount` là tỷ lệ giá bán / giá gốc; 51% số dòng có giá dưới giá gốc.
  - `holiday_flag` đánh dấu cả cuối tuần và các ngày lễ (Thanh Minh, 1/5, Đoan Ngọ).
  - Mỗi điểm bán có từ 1 đến 164 mặt hàng (trung vị 50).
- **Khác với cửa hàng tiện lợi:** điểm bán FRN là **kho giao hàng online 30 phút**, không phải cửa hàng có khách vào mua. Hồ sơ theo giờ là giờ đặt đơn online (đỉnh 9–10h và 16–17h).

## 3. Thiết kế

### Chia dữ liệu chống rò rỉ

- **Theo điểm bán:** 50 điểm **giữ lại**, gồm điểm demo 18 (164 mặt hàng), không bao giờ dùng để huấn luyện. Mọi số đánh giá đều đo trên các điểm này.
- **Theo thời gian:** có hai mô hình.
  - **Mô hình chạy thật** (`q10/q50/q90.txt`): học trên dữ liệu đến ngày thứ 90, đánh giá trên tuần eval (ngày 91–97).
  - **Mô hình backtest** (`bt_q*.txt`): chỉ học đến ngày thứ 60, nên đoạn so sánh A/B (ngày 61–97) là dữ liệu mô hình chưa từng thấy, kể cả qua các điểm bán khác cùng ngày.

### Nhu cầu bị chặn khi hết hàng

- Ngày hết hàng thì số bán thấp hơn nhu cầu. OC khôi phục nhu cầu bằng **hồ sơ bán theo giờ**: nhu cầu = số bán ÷ tỷ trọng nhu cầu rơi vào các giờ còn hàng.
- Hồ sơ giờ lấy từ chính chuỗi đó trên những ngày còn hàng đủ giờ. Nếu chuỗi có dưới 5 ngày như vậy thì dùng hồ sơ của nhóm hàng cấp 1.
- Ngày hết hàng gần như cả ngày (các giờ còn hàng chỉ chiếm dưới 30% nhu cầu) thì lấy trung bình cùng thứ.
- **Kiểm chứng:** che các giờ cuối ngày trên những ngày còn hàng đủ giờ (giả lập "bán hết từ giờ k"), rồi so ước tính với số thật (mục 5).

### Đặc trưng (`backend/app/engines/ml_features.py`, dùng chung cho Kaggle và OC)

- **Chỉ dùng thứ cửa hàng biết lúc đặt hàng:** số bán theo ngày, cờ hết hàng theo ngày, thứ trong tuần, ngày lễ, khuyến mãi đã lên lịch, mã nhóm hàng. **Không dùng thời tiết** của ngày cần dự báo.
- **Ngày hết hàng trong cửa sổ 28 ngày** được thay bằng `max(số bán, trung bình cùng thứ của các ngày còn hàng)`, tức là chỉ nâng lên, không bao giờ kéo xuống.
- **Đích học** là tỷ lệ so với mức nền 28 ngày, nên một mô hình dùng chung cho mọi quy mô bán (test `test_features_shape_and_scale_free`).
- **Đích chỉ lấy những ngày không hết hàng nặng** (các giờ còn hàng chiếm ít nhất 50% nhu cầu); giá trị đích là nhu cầu đã khôi phục.
- **Không quy về giá gốc.** Mô hình dự báo nhu cầu thật đúng như đã xảy ra, coi khuyến mãi của FRN là biến động OC không biết trước. Không dùng giảm giá hay khuyến mãi của ngày cần dự báo làm đặc trưng, vì OC không biết trước.
  - Phiên bản 2 đã thử quy chuỗi về giá gốc bằng hệ số 1 + e × mức giảm. Kết quả: mọi phương pháp, kể cả EWMA, đều dự báo thấp hơn thực tế 14–31% trên những ngày bán giá gốc, vì hệ số e ước lượng được quá lớn (mục 5.4).
- **Dự báo EWMA của OC là một đặc trưng.** LightGBM học cách sửa sai cho engine cũ, thay vì học lại từ đầu.

### Mô hình

- Ba mô hình LightGBM hồi quy phân vị (q = 0,1 / 0,5 / 0,9), học trên toàn bộ 16,9 triệu mẫu (mọi mốc dự báo × 7 khoảng cách × 47.325 chuỗi của 848 điểm huấn luyện).
- **Dò tham số** cho q50 trên 30% số mẫu, 7 cấu hình (num_leaves 63–511, min_data_in_leaf 50–500, có/không L2, feature_fraction, max_bin). Các cấu hình gần như ngang nhau (pinball 0,2496–0,2497), tức mô hình không nhạy với độ phức tạp. Chọn num_leaves 127, min_data_in_leaf 200.
- **Huấn luyện** với tốc độ học 0,03, kiểm tra sớm trên 7 ngày cuối của các điểm huấn luyện: q50 502 vòng, q10 677, q90 310.
- **Học lại trên toàn bộ dữ liệu**, gồm cả 7 ngày gần ngày dự báo nhất, với số vòng tốt nhất × 1,1. Mô hình OC dùng là bản học lại này.
- Cả lần chạy hết 2,5 giờ CPU trên Kaggle, trong ngân sách 10,6 giờ. Các mô hình hội tụ sớm, và dò tham số cho thấy không còn nhiều chỗ để cải thiện bằng tham số.
- OC dùng q50 làm dự báo. Độ lệch σ = (q90 − q10) / 2,563, để các engine đặt hàng, xử lý cận date và tính trần HSD hiện có dùng nguyên được. Bộ chọn theo lãi (mục 5.7) quyết định σ nào được dùng để đặt hàng. Hiện app dùng dự báo q50 của LightGBM với σ của EWMA, vì dùng thẳng khoảng của LightGBM (đối xứng hay lệch) làm đặt dư.

### Chọn nhóm dùng ML

- Mặt hàng được chia theo **mức bán** (3 bậc, ngưỡng tính trên các điểm huấn luyện) × **mức lắt nhắt** (trên 30% số ngày bán 0).
- LightGBM chỉ được dùng ở nhóm mà, trên tuần eval của các điểm giữ lại, nó **thắng EWMA về cả WAPE lẫn pinball q50**, và độ phủ khoảng 80% không kém hơn quá 5 điểm. Các nhóm còn lại vẫn dùng EWMA.
- Danh sách nhóm ghi trong `meta.json` (`use_ml_segments`).
- **Từ mục 5.7, app chọn theo lãi thay vì sai số dự báo.** Có `backend/app/ml/artifacts/decision_gate.json` thì bộ chọn dự báo (`backend/app/engines/forecast_router.py`) dùng nhóm hàng × quy mô điểm bán trong file đó. Quy mô của cửa hàng demo là 164 mặt hàng FRN. Thiếu file hoặc file hỏng thì dùng lại `use_ml_segments`.

### Đơn vị

- Số bán FRN × **K = 10** ra số đơn vị hàng của cửa hàng OC. Đây là giả định, để mặt hàng trung vị bán khoảng 7 đơn vị/ngày.
- Engine EWMA được chạy ở đơn vị cửa hàng, vì sàn Poisson của nó (σ ≥ √mức nền) phụ thuộc đơn vị.

## 4. Những gì của cửa hàng OC vẫn là giả định

FRN chỉ cho nhu cầu. Các phần sau được tạo theo quy tắc cố định từ mã số (`backend/app/sim/frn_catalog.py`):
- tên hàng: dạng trung tính "Mặt hàng 412 · nhóm 3.10", vì FRN không cho biết nhóm nào là rau, thịt hay hải sản;
- giá bán (12.000–80.000đ), giá vốn (62–75% giá bán), HSD 1–3 ngày, quy cách 1;
- nhà cung cấp: mỗi nhóm quản lý một nhà cung cấp hư cấu, giao hằng ngày, chờ hàng 1 ngày;
- 5 mặt hàng bán nhiều nhất được coi là hàng kéo khách.

Phần vận hành (lô, đơn, sổ sách 90 ngày) được mô phỏng bằng chính sách "kinh nghiệm" trên nhu cầu thật.

## 5. Kết quả

### 5.1 Khôi phục nhu cầu ngày hết hàng

Che các giờ cuối ngày trên 200.000 ngày còn hàng đủ giờ, rồi so ước tính với số bán thật:

| Cách tính | Sai số (WAPE) | Độ lệch |
|---|---|---|
| Khôi phục theo hồ sơ bán theo giờ | 20,5% | −0,1% |
| Coi số bán là nhu cầu | 32,3% | −32,3% |

### 5.2 Các phiên bản đã chạy

| Phiên bản | Thay đổi | Điều rút ra |
|---|---|---|
| 1 | LightGBM có đặc trưng giảm giá của ngày đích. Khi chấm, giả định ngày đích không khuyến mãi | LightGBM WAPE 34,3% so với EWMA 35,1%, nhưng **lệch thấp 15,7%**: ngày đích thật có khuyến mãi mà mô hình dự báo ở giá gốc. Backtest điểm demo: hết hàng cao hơn A |
| 2 | Quy chuỗi về giá gốc bằng độ co giãn ước lượng | e ≈ 9,6, không hợp lý. Mọi phương pháp lệch thấp 14–31%. Bỏ cách này |
| 3 | Nhu cầu thô; thêm dự báo EWMA làm đặc trưng; dùng toàn bộ dữ liệu; dò tham số; học lại trên toàn bộ | **LightGBM WAPE 30,2% so với EWMA 35,1%, độ lệch +2,7% so với +6,9%, độ phủ khoảng 80% là 81% so với 73%.** Dùng trong OC |

### 5.3 Sai số dự báo, phiên bản 3

Đo trên 50 điểm giữ lại (2.675 chuỗi), dự báo 1–7 ngày tới. WAPE = tổng |sai| / tổng thực tế. Độ phủ = tỷ lệ ngày thực tế nằm trong khoảng q10–q90 (lý tưởng là 80%).

**Tuần đánh giá chính thức của FRN** (26/06–02/07; mô hình học đến 25/06), trên những ngày còn hàng đủ giờ (11.037 điểm):

| Phương pháp | WAPE | Độ lệch | Độ phủ 80% |
|---|---|---|---|
| **LightGBM** | **30,2%** | **+2,7%** | **81%** |
| Engine EWMA của OC | 35,1% | +6,9% | 73% |
| EWMA bỏ cờ hết hàng | 35,1% | −10,8% | 76% |
| Trung bình 28 ngày | 35,5% | −11,0% | — |
| Cùng thứ tuần trước | 38,7% | −0,7% | — |

**Đánh giá cuốn chiếu 37 ngày** (27/05–02/07, mỗi ngày một mốc, mô hình backtest chỉ học đến 26/05), 374.982 điểm: LightGBM **35,0%** so với EWMA 37,8%; độ phủ 80% so với 72%.

**Theo nhóm hàng** (tuần đánh giá):

| Nhóm | Số điểm | LightGBM | EWMA | Dùng ML |
|---|---|---|---|---|
| Bán chạy, đều | 3.407 | 24,6% | 29,2% | có |
| Bán vừa, đều | 3.642 | 37,0% | 42,1% | có |
| Bán ít, đều | 3.842 | 42,4% | 48,3% | có |
| Bán vừa, lắt nhắt | 39 | 35,1% | 39,4% | có |
| Bán ít, lắt nhắt | 101 | 45,6% | 49,2% | có |
| Bán chạy, lắt nhắt | 6 | 46,5% | 38,4% | **không**, giữ EWMA |

**Nhận xét:**
- LightGBM thắng EWMA ở mọi tập đánh giá: ngày còn hàng, nhu cầu đã khôi phục, ngày bán giá gốc, tuần eval, cuốn chiếu. Ngoại lệ duy nhất là nhóm "bán chạy, lắt nhắt", vốn rất ít dữ liệu.
- Mức lợi rõ nhất ở **độ tin cậy của khoảng dự báo**: 80% so với 72–73%. Đây là thứ engine đặt hàng dùng để tính tồn an toàn.
- **Đặc trưng quan trọng nhất** (theo gain): nhóm hàng cấp 2, **dự báo của EWMA**, thứ của ngày đích, trung bình 7 ngày, mức nền. Mô hình học cách sửa sai cho engine cũ, không thay hẳn nó.
- **Tham khảo** (không cùng điều kiện, chỉ để biết cỡ): bài báo FRN báo WAPE 29–32% cho mô hình TFT trên cùng bộ dữ liệu, với thiết lập khác.

### 5.4 Độ co giãn khi giảm giá: FRN không dùng được

- Ước lượng theo dạng OC dùng (bán tăng ≈ 1 + e × mức giảm), trên những ngày còn hàng đủ giờ, so với trung bình cùng thứ của những ngày giá gốc:
  - gộp cả ngày có khuyến mãi: e ≈ 5,0 (khoảng tin cậy 90%: 4,9–5,1);
  - bỏ những ngày có cờ khuyến mãi: e ≈ 9,6.
- Hai con số đều phi lý: giảm 10% giá mà bán tăng 50–96%. Giải thích hợp lý nhất là **giá của Dingdong nội sinh**: họ giảm giá đúng vào lúc hoặc đúng mặt hàng mà nhu cầu đang cao, nên so sánh ngày giảm giá với ngày không giảm giá không đo được tác động của giá.
- **Vì vậy:**
  - OC **không** lấy độ co giãn từ FRN; engine giữ giả định 3,0. Cấu hình `ELASTICITY_FROM_FRN=false` mặc định; bật lên chỉ để thử nghiệm.
  - Thế giới backtest giữ mức tham chiếu cũ: khách phản ứng bằng 50% mức engine tin, kèm các dòng độ nhạy 25% và 100%.
- Đây là một **kết quả âm có giá trị**: không nên học độ co giãn từ lịch sử giá của nhà bán lẻ, vì giá không được đặt ngẫu nhiên. Muốn đo đúng phải thử nghiệm giá.

### 5.5 Khung giờ bán

Tỷ trọng bán theo 4 khung giờ (6–11h, 11–14h, 14–17h, 17–22h), tính trên các điểm huấn luyện cho từng nhóm quản lý, lấy từ `dayparts.json`. Đỉnh rơi vào buổi sáng hoặc buổi tối tùy nhóm, nên giờ giảm giá cuối ngày được tính theo từng nhóm.

### 5.6 Backtest A/B trên các điểm giữ lại

**Thiết lập:**
- 50 điểm bán giữ lại, mỗi điểm chạy trên **nhu cầu thật** đã khôi phục của chính nó.
- Khởi động 27/03–26/05 bằng chính sách "kinh nghiệm", rồi so sánh 37 ngày (27/05–02/07) với cùng một điểm xuất phát.
- Ba chính sách chính (các biến thể khác ở mục 5.7):
  - **A:** kinh nghiệm, có giờ vàng 30%;
  - **B-EWMA:** Ops Chest với engine cũ;
  - **B-ML:** Ops Chest với bộ chọn LightGBM, dùng mô hình backtest chỉ học đến 26/05.
- Chạy bằng `python -m app.sim.backtest --frn`; kết quả trong `backend/app/sim/data/frn/backtest.json`.

**Trung vị qua 50 điểm** (khoảng tứ phân vị trong ngoặc):

| | A | B-EWMA | B-ML |
|---|---|---|---|
| Lãi gộp so với A | — | **+4,2%** (−0,1% đến +5,1%) | +3,7% (−1,4% đến +4,9%) |
| Tỷ lệ hủy | 5,3% | 5,2% | 5,7% |
| Tỷ lệ hết hàng | 14,5% | 13,6% | **13,2%** |
| Hết hàng của hàng kéo khách | 8,7% | 3,9% | **2,7%** |

- B-ML lãi hơn A ở **68%** số điểm, và không hết hàng nhiều hơn A ở **92%** số điểm.
- B-ML lãi hơn B-EWMA chỉ ở **34%** số điểm (trung vị −0,4%).
  - Điểm bán dưới 30 mặt hàng (12 điểm): trung vị −4,7%, tệ nhất −16%.
  - Điểm bán từ 30 mặt hàng (38 điểm): −0,3%.
  - Điểm demo 18 (164 mặt hàng): +0,4% (B-ML +4,6% so với A, B-EWMA +4,2%).

**Kịch bản độ nhạy** (B-gate của mục 5.7, tức bộ chọn ngoài mẫu của từng điểm, so với A; trung vị trên 20 điểm):

| Kịch bản | Lãi | Hủy A / B | Hết hàng A / B |
|---|---|---|---|
| Tham chiếu | +5,5% | 5,3% / 4,5% | 14,9% / 14,5% |
| Khách phản ứng bằng nửa tham chiếu (25% mức engine tin) | +4,7% | 5,4% / 4,9% | 15,1% / 14,5% |
| Khách phản ứng bằng 1/4 tham chiếu (12,5%) | +4,5% | 5,5% / 5,1% | 15,1% / 14,5% |
| Store Manager duyệt 80% | +4,6% | 5,3% / 4,8% | 14,9% / 14,6% |
| Store Manager duyệt 60% | +3,7% | 5,3% / 5,0% | 14,9% / 14,4% |
| B không có sàn mức phục vụ | −0,6% | 5,3% / 2,8% | 14,9% / **22,2%** |
| Giờ giảm giá cố định 18h | +5,5% | 5,3% / 4,5% | 14,9% / 14,5% |
| B chỉ đặt hàng (tắt giảm giá, trả NCC) | +4,7% | 5,3% / 5,2% | 14,9% / 14,5% |

**Đọc kết quả, nói thẳng:**
1. **Dự báo chính xác hơn chưa biến thành lãi nhiều hơn.** LightGBM sai ít hơn EWMA ở mọi tập đánh giá, nhưng trong backtest nó giảm hết hàng và tăng hủy, nên lãi trung vị hơi thấp hơn. Lý do hợp lý nhất: khoảng dự báo của LightGBM rộng và đúng hơn (độ phủ 80% so với 72%). Engine đặt hàng chuyển σ thành tồn an toàn, nên LightGBM đặt nhiều hơn. Với hàng tươi biên lãi mỏng (giá vốn giả định 62–75%), phần hủy thêm ăn mất phần lãi do bớt hết hàng. EWMA đặt ít hơn vì khoảng của nó hẹp quá mức, tức "đúng" một cách tình cờ.
2. **Phần giá trị chắc chắn của OC** nằm ở sàn mức phục vụ và cách đặt hàng có trần HSD. Bỏ sàn thì hết hàng tăng lên 22,2% và lãi không còn.
3. Giờ giảm giá theo khung bán (11h hay 18h) **không tạo khác biệt** trong backtest này: với HSD 1–3 ngày và đơn hằng ngày, gần như không còn hàng dư cuối ngày để giảm giá.
4. Bộ chọn ở mục này (B-ML) chọn theo sai số dự báo. Mục 5.7 thử hai hướng: dùng thẳng phân vị của mô hình, và chọn theo lãi với kiểm chéo theo điểm bán. **Kết quả: dùng thẳng phân vị lệch thì tệ hơn (−2,2%). Dùng dự báo điểm của LightGBM với σ của EWMA, chọn theo lãi, thì hơn EWMA +0,8% ngoài mẫu và thắng ở 78% số điểm.**

### 5.7 Chọn theo lãi và dùng phân vị

Mục 5.6 cho thấy dự báo tốt hơn chưa thành lãi nhiều hơn. Phần này thử ba cách đặt hàng với LightGBM và chọn giữa chúng theo lãi. **Không huấn luyện lại mô hình** (vẫn dùng `bt_q*`).

**Ba biến thể đặt hàng với LightGBM** (biến thể ứng viên của bộ chọn):
- **sym (cách cũ):** dự báo q50, σ đối xứng = (q90 − q10)/2,563.
- **split (phân phối lệch):** split-normal khớp đúng q10/q50/q90: `σ_dưới = TB(q50 − q10)/1,2816`, `σ_trên = TB(q90 − q50)/1,2816`. Engine đặt hàng (`compute_order`) lấy σ_trên khi z ≥ 0 (tồn an toàn ở mức phục vụ trên 50%, trần HSD) và σ_dưới khi z < 0. EWMA không có hai trường này nên vẫn chạy y như cũ.
- **ewma_sigma:** dự báo điểm q50 của LightGBM, nhưng tồn an toàn và trần HSD tính bằng σ của engine EWMA cho cùng mặt hàng. Router ghép hai engine (`forecast_router.py`).

**Chọn theo lãi** (`choose_gate` trong `backend/app/sim/backtest.py`):
- Nhóm = nhóm hàng của mục 3 (mức bán × mức lắt nhắt, tính lúc T0) × **quy mô điểm bán** (số mặt hàng FRN; ngưỡng 30, 50 hoặc 75, hoặc không chia).
- Giá trị của một nhóm = tổng (lãi mặt hàng khi dùng LightGBM − lãi khi dùng EWMA) / lãi B-EWMA của điểm. Lãi mặt hàng = doanh thu − giá vốn − giá vốn hàng hủy. Chia theo lãi của điểm để điểm lớn không lấn át điểm nhỏ.
- Nhóm có giá trị dương thì dùng ML. Biến thể và ngưỡng quy mô được chọn để tổng giá trị lớn nhất.

**Chọn ngoài mẫu: kiểm chéo 2 lần theo điểm bán.**
- 50 điểm chia thành 2 nửa cố định (seed 0), cân theo quy mô: xếp theo số mặt hàng, mỗi cặp liền kề chia ngẫu nhiên mỗi nửa một điểm.
- Bộ chọn của nửa 0 chỉ học từ nửa 1, và ngược lại. Sau đó chạy **mô phỏng thật** chính sách B-gate trên nửa còn lại. Không cộng lãi theo mặt hàng, vì các mặt hàng thay thế nhau.
- Vì vậy kết quả B-gate của mọi điểm đều là **ngoài mẫu**.
- Bộ chọn cho app học trên cả 50 điểm và ghi vào `backend/app/ml/artifacts/decision_gate.json`. Nó được chọn bằng mô hình backtest `bt_` rồi áp cho mô hình chạy thật `q*`.

**Kết quả** (trung vị qua 50 điểm, khoảng tứ phân vị trong ngoặc):

| | Lãi so với A | So với B-EWMA | Điểm thắng B-EWMA | Hủy | Hết hàng | Hết hàng kéo khách |
|---|---|---|---|---|---|---|
| B-EWMA | +4,2% (−0,1% đến +5,1%) | — | — | 5,2% | 13,6% | 3,9% |
| B-ML, bộ chọn cũ (sym) | +3,7% (−1,4% đến +4,9%) | −0,4% (−1,7% đến +0,5%) | 34% | 5,7% | 13,2% | 2,7% |
| B-ML split, mọi mặt hàng | +1,7% (−3,8% đến +3,5%) | −2,2% (−3,6% đến −1,1%) | 6% | 6,4% | 12,3% | 2,2% |
| B-ML ewma_sigma, mọi mặt hàng | +4,4% (+1,3% đến +6,2%) | +0,9% (+0,0% đến +1,5%) | 76% | 4,8% | 14,2% | 3,4% |
| **B-gate** (chọn theo lãi, ngoài mẫu) | **+4,8%** (+1,2% đến +6,4%) | **+0,8%** (+0,1% đến +1,4%) | **78%** | **4,8%** | 14,0% | 3,4% |

- Bộ chọn cũ trong `meta.json` loại đúng một nhóm (bán chạy · lắt nhắt), và nhóm này gần như không có mặt hàng. Vì vậy "B-ML, bộ chọn cũ" trùng với "sym ở mọi mặt hàng".
- **B-gate so với B-EWMA:** thấp nhất −1,7%, cao nhất +4,0%. Theo quy mô:
  - 13 điểm từ 30 mặt hàng trở xuống: +0,4%;
  - 37 điểm trên 30 mặt hàng: +0,9%.
- B-gate lãi hơn A ở 76% số điểm (B-EWMA: 72%). Hết hàng không nhiều hơn A ở 74% số điểm (B-ML cũ: 92%).
- **Điểm demo 18** (164 mặt hàng, thuộc nửa 0): B-gate +0,6% so với B-EWMA.
- **Kịch bản độ nhạy** ở mục 5.6 nay chạy bằng B-gate (bộ chọn ngoài mẫu của từng điểm).

**Bộ chọn được chọn:**
- Cả hai nửa và bản cho app đều chọn **ewma_sigma, ngưỡng 30 mặt hàng**. Ở mọi ngưỡng, ewma_sigma đều hơn sym và split.
- Bản cho app dùng LightGBM cho:
  - điểm lớn (trên 30 mặt hàng): bán chạy · đều (889 mặt hàng-điểm, +80 triệu đ trên 50 điểm), bán vừa · đều (832, +41 triệu đ), bán ít · đều (655; dương sau khi chia theo lãi của điểm, nhưng tổng tiền −2,8 triệu đ, tức gần như hòa), bán ít · lắt nhắt (chỉ 4, gần như nhiễu);
  - điểm nhỏ: bán vừa · đều (110, +3 triệu đ).
- Giữ EWMA cho bán chạy và bán ít ở điểm nhỏ.
- Hai nửa chọn gần giống nhau: nửa 0 không có "bán ít · đều · điểm lớn".
- Ở cửa hàng demo, cả **164 mặt hàng dùng dự báo LightGBM**, với tồn an toàn theo σ của EWMA.

**Đọc kết quả, nói thẳng:**
1. **LightGBM làm OC lãi hơn khi chỉ dùng dự báo điểm của nó.** Ngoài mẫu, B-gate hơn B-EWMA +0,8% (trung vị) và thắng ở 78% số điểm; khoảng tứ phân vị nằm hẳn trên 0. Hủy giảm từ 5,2% còn 4,8%. Hết hàng của hàng kéo khách giảm từ 3,9% còn 3,4%. Đổi lại, hết hàng chung nhích lên (13,6% → 14,0%).
2. **Phần lớn lợi ích đến từ biến thể, không phải từ việc chọn nhóm.** Dùng ewma_sigma ở mọi mặt hàng, không chọn gì, đã được +0,9% và thắng 76% số điểm. Bộ chọn chủ yếu bỏ những nhóm nhỏ nơi biến thể này hòa hoặc thua.
3. **Dùng thẳng khoảng dự báo của LightGBM thì lỗ.**
   - Khoảng của LightGBM rộng và trung thực hơn (độ phủ 81% so với 73%). Đi qua sàn mức phục vụ 90–95%, nó thành đặt dư: sym −0,4%, split −2,2%. Split tệ hơn vì phía trên của LightGBM dày hơn phía dưới, mà sàn cao dùng đúng phía trên.
   - Ghép dự báo điểm của LightGBM với σ hẹp hơn của EWMA cho kết quả tốt nhất. Điều này cho thấy với cấu trúc giá giả định (giá vốn 62–75%), sàn mức phục vụ đang cao hơn mức tối ưu theo lãi. σ "sai nhưng hẹp" của EWMA bù lại phần đó.
   - Hướng sạch hơn là dùng σ trung thực của mô hình và hạ sàn cho hàng tươi. Hướng này chưa thử, vì sàn là quyết định vận hành (giữ khách), không chỉ là bài toán lãi.
4. **Giới hạn của con số này:**
   - Biến thể ewma_sigma ban đầu chỉ là chẩn đoán. Nó được đưa vào làm ứng viên **sau khi** đã thấy kết quả của nó trên chính 50 điểm này.
   - Kiểm chéo bảo vệ bước chọn nhóm và biến thể, nhưng không xóa được việc người làm đã nhìn kết quả trước khi thêm ứng viên. Vì vậy +0,8% nên đọc là ước lượng hơi lạc quan.
   - Muốn xác nhận cần các điểm FRN chưa dùng ở bước nào, hoặc một giai đoạn sau ngày 02/07/2024.

## 6. Giới hạn cần nói rõ

1. FRN là kho giao hàng online ở Trung Quốc, chỉ có hàng tươi, trong 97 ngày. Không có Tết, không có mùa vụ, không có hàng dài ngày.
2. Hệ số K, giá, giá vốn, HSD và nhà cung cấp đều là giả định. Lãi và tỷ lệ hủy trong backtest phụ thuộc vào chúng.
3. Giảm giá trong FRN là khuyến mãi, không phải giảm vì cận hạn, nên độ co giãn chỉ là xấp xỉ. Ngoài ra, giá trong FRN có thể không độc lập với nhu cầu (nội sinh).
4. Khôi phục nhu cầu theo hồ sơ giờ là cách đơn giản, không phải mô hình khôi phục của bài báo.
5. Backtest vẫn mô phỏng phần vận hành. Chỉ nhu cầu là thật.
