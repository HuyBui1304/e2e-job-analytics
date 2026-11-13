# Quy tắc chuẩn hoá tầng Silver

Tài liệu này là "hợp đồng dữ liệu" của Silver: mỗi cột Silver lấy từ đâu, biến đổi theo quy tắc nào.
Mọi ví dụ "đầu vào" bên dưới đều lấy từ dữ liệu crawl thật ngày 2026-11-13 (30 tin × 4 web).

Ký hiệu:
- **[Gốc]**: làm giống project gốc (`src/transform/standardizers.py`, `job_standardizer.py`).
- **[Đề xuất]**: khác project gốc, có ghi lý do.
- **[Cần chốt]**: chưa quyết, cần chọn trước khi viết code.

---

## 0. Đầu vào và đầu ra

| | |
|---|---|
| Đầu vào | `my_catalog.bronze.<web>_jobs`, lọc đúng một `ingest_date` |
| Đầu ra | **[Cần chốt]** xem mục 12 |
| Cách ghi | `MERGE INTO` theo `job_id` **[Gốc]** |
| Dòng không đạt | Bảng DLQ kèm lý do **[Gốc]** |

---

## 1. Bộ cột Silver và ánh xạ từ từng web

| Cột Silver | TopCV | CareerViet | ITviec | VietnamWorks |
|---|---|---|---|---|
| `source` | `source` | `source` | `source` | `source` |
| `source_job_id` | `job_id` | `job_id` | `job_id` | `job_id` |
| `job_url` | `job_url` | `job_url` | `job_url` | `job_url` |
| `job_title` | `job_title` | `job_title` | `job_title` | `job_title` |
| `company_name` | `company_name` | `company_name` | `company_name` | `company_name` |
| `company_url` | `company_url` | `company_url` | `company_url` | `company_url` |
| `company_industry` | `company_field` | `industry` | `company_industry` | `job_industry` |
| `company_size_raw` | `company_size` | — | `company_size` | — |
| `salary_raw` | `salary` | `salary` | `salary_value` (JSON-LD) | `salary` |
| `experience_raw` | `experience` | `experience` | `experience_months` | `experience` |
| `level_raw` | `level` | `level` | — | `level` |
| `education_raw` | `education` | `education` | — | `education` |
| `working_type_raw` | `working_type` | — | `working_type` | — |
| `locations_raw` | `location_regions` | `location_regions` | `location_regions` | `location_regions` |
| `deadline_raw` | `deadline` | `deadline` | `valid_through` | `valid_through` |
| `date_posted` | `date_posted` | `date_posted` | `date_posted` | `date_posted` |
| `skills_raw` (gộp) | `skills` + `skills_required` + `skills_preferred` | `skills` + `job_tags` | `skills` + `skills_tags` | `skills` + `skills_tags` |
| `description`, `requirements` | có | có | có | có |

Cột nào web không có thì để `null`. Các cột riêng khác của từng web (ví dụ `probation`, `top_reasons`, `cv_language`) **không** đưa lên Silver; vẫn tra được ở Bronze.

---

## 2. Lương

**Đầu ra:** `salary_min`, `salary_max` (số), `salary_currency` (`VND` / `USD` / null), `salary_negotiable` (true/false), `salary_band`.

**Đơn vị:** VND tính theo **triệu đồng/tháng** **[Gốc]**, USD tính theo **USD/tháng**.

| Đầu vào thật | min | max | currency | negotiable |
|---|---|---|---|---|
| `Thoả thuận`, `Cạnh tranh`, `Thương lượng`, null | null | null | null | true |
| `Very Attractive!!!` (ITviec) | null | null | null | true |
| `10 - 30 triệu` | 10 | 30 | VND | false |
| `30 - 50 Triệu VND` | 30 | 50 | VND | false |
| `12tr-17tr ₫/tháng` | 12 | 17 | VND | false |
| `Tới 20 triệu`, `Lên đến 35 Triệu VND` | null | 20 / 35 | VND | false |
| `$ 1,000-2,000 /tháng` | 1000 | 2000 | USD | false |
| `Tới $ 2,500 /tháng` | null | 2500 | USD | false |
| `$ 30tr-50tr /tháng` (VNW ghi lẫn) | 30 | 50 | VND | false |
| ITviec: JSON-LD `salary_min=850, salary_max=1300` | 850 | 1300 | USD | false |

Quy tắc:
1. Có `tr` hoặc `triệu` → VND, **kể cả khi có ký hiệu `$`**. Không có mà có `$` hoặc `usd` → USD.
2. USD: bỏ dấu phẩy ngăn nghìn (`1,000` → 1000). VND: dấu phẩy là phần thập phân (`12,5` → 12.5) **[Gốc]**.
3. Bắt đầu bằng `tới`, `lên đến`, `up to`, `dưới` → chỉ có `max`. Bắt đầu bằng `từ`, `trên` → chỉ có `min`.
   **[Đề xuất]** Bản gốc thiếu `lên đến`, nên `Lên đến 35 Triệu` bị hiểu thành `min = 35`. Sai nghĩa.
4. **Không tin** `salary_unit` và `salary_currency` từ JSON-LD: VietnamWorks luôn ghi `HOUR`/`USD`, CareerViet có `LTT`.
5. **[Đề xuất]** Giá trị vô lý coi như không có lương: VND < 1 triệu hoặc USD < 100 (ví dụ `$ 1-1`), hoặc `min > max`.
6. `salary_band` theo triệu VND, USD quy đổi tỉ giá cố định 25.000 VND/USD **[Gốc]**:
   `Negotiable`, `< 10tr`, `10tr - 20tr`, `20tr - 30tr`, `> 30tr`.

---

## 3. Kinh nghiệm

**Đầu ra:** `exp_min_years`, `exp_max_years` (số nguyên).
**[Đề xuất]** Bản gốc chỉ ra chuỗi (`"> 5 years"`), không lọc hay tính trung bình được.

| Đầu vào thật | min | max |
|---|---|---|
| `Không yêu cầu`, `Không yêu cầu kinh nghiệm` | 0 | 0 |
| `2 năm` (TopCV), `3 Năm`, `3` (VietnamWorks) | 2 / 3 / 3 | null |
| `Trên 3 Năm` | 3 | null |
| `3 - 5 Năm`, `12 - 15 Năm` | 3 / 12 | 5 / 15 |
| `Lên đến 3 Năm` | 0 | 3 |
| ITviec `experience_months = 37 / 10 / 61` | 3 / 0 / 5 | null |

ITviec quy đổi: `exp_min_years = floor(months / 12)`.

---

## 4. Cấp bậc

**Đầu ra:** `level` thuộc `Intern`, `Fresher`, `Junior`, `Middle`, `Senior`, `Lead`, `Manager`, `Director`.

Giá trị thật: `Nhân viên`, `Trưởng nhóm`, `Quản lý`, `Quản lý / Giám sát`, `Trưởng phòng`, `Mới Tốt Nghiệp`.
Ánh xạ theo `LEVEL_MAPPING` **[Gốc]**: nhân viên → Junior, mới tốt nghiệp → Fresher, trưởng nhóm → Lead,
quản lý / trưởng phòng / giám sát → Manager, giám đốc → Director.

**[Cần chốt]** 83% tin ghi "Nhân viên", và ITviec không có cột cấp bậc. Đề xuất: nếu **tiêu đề** có
`intern`, `fresher`, `junior`, `middle`, `senior`, `lead`, `manager` thì ưu tiên tiêu đề
(ví dụ "Senior Data Engineer" ghi cấp "Nhân viên" → Senior).

---

## 5. Địa điểm

**Đầu ra:** `locations` (danh sách tỉnh/thành chuẩn), `location_primary` (phần tử đầu).

- **[Đề xuất]** Dùng `location_regions` (từ JSON-LD) thay vì `place`. `place` có dạng khó tách như
  `Hà Nội và 2 nơi khác`, `Hà Nội | Hồ Chí Minh`; `location_regions` đã là danh sách sạch.
- Chuẩn hoá tên theo `LOCATION_MAPPING` **[Gốc]** (`tp.hcm`, `ho chi minh`, `sài gòn` → `Hồ Chí Minh`…).
- **[Cần chốt]** Từ 7/2025 Việt Nam sáp nhập tỉnh (ví dụ Bình Dương nhập vào TP.HCM), nhưng các web vẫn ghi
  tên cũ. Giữ tên như web ghi, hay quy về đơn vị hành chính mới?

---

## 6. Hạn nộp

**Đầu ra:** `deadline_date` (kiểu ngày).

| Web | Đầu vào thật | Cách đọc |
|---|---|---|
| TopCV, CareerViet | `13/12/2026` | `to_date(..., 'dd/MM/yyyy')` |
| ITviec, VietnamWorks | `valid_through = 2026-12-10` | `to_date(...)` |

Không đọc được thì lấy `valid_through`.
**[Đề xuất]** Bản gốc lấy **số đầu tiên** trong chuỗi làm "số ngày còn lại", nên `13/12/2026` thành "còn 13 ngày". Sai.

---

## 7. Hình thức làm việc

**Đầu ra:** `working_type` thuộc `Onsite`, `Hybrid`, `Remote` **[Gốc]**.

| Đầu vào thật | Kết quả |
|---|---|
| `Làm việc tại văn phòng / Onsite`, `Tại văn phòng` | Onsite |
| `Linh hoạt` (ITviec) | Hybrid |
| `Làm từ xa` | Remote |
| `Làm việc từ xa (Remote), Làm việc tại văn phòng / Onsite` | Hybrid **[Đề xuất]**: có cả hai thì là Hybrid |

CareerViet, VietnamWorks không có trường này → null.

---

## 8. Học vấn, quy mô công ty

- `education`: `Đại Học trở lên` / `Đại học` → `Đại học`; tương tự `Cao đẳng`, `Trung cấp`.
- `company_size`: `25-99 nhân viên` → `25-99`, `1000+ nhân viên` → `1000+` **[Gốc]**.
  Mỗi web chia khoảng khác nhau (TopCV `25-99`, ITviec `51-150`) nên thêm `company_size_group`:
  `Small` (< 100), `Medium` (100–499), `Large` (500–999), `Enterprise` (1000+) **[Đề xuất]**, xếp theo cận dưới.

---

## 9. Kỹ năng

**Đầu ra:** `skills` (danh sách).

1. Gộp các cột kỹ năng của web (bảng mục 1), bỏ khoảng trắng thừa, bỏ phần tử rỗng **[Gốc]**.
2. **[Đề xuất]** Bỏ trùng không phân biệt hoa thường (`SQL` và `sql` là một).
3. Bổ sung kỹ năng tìm thấy trong tiêu đề theo danh sách từ khoá **[Gốc]** (`enrich_skills_from_title`).

---

## 10. Nhóm nghề

**Đầu ra:** `job_category`, theo từ khoá trong tiêu đề **[Gốc]**:
Data Engineer, Data Analyst, Data Scientist, AI Engineer, Fullstack, Backend, Frontend, Mobile,
DevOps / SRE, QA/QC, Project Manager, Business Analyst, Security / IT Support, Others.

- **[Đề xuất]** Bản gốc nối điều kiện trong vòng `for` nên **nhóm khai báo sau cùng thắng**.
  "Data Engineer (Python, SQL)" bị xếp vào Backend vì Backend có từ khoá `python`.
  Sửa: đặt **thứ tự ưu tiên rõ ràng, khớp nhóm đầu tiên là dừng**, và có test cho trường hợp này.
- **[Cần chốt]** Bộ lọc "Công nghệ thông tin" của các web vẫn có tin không phải IT
  (Thiết kế đồ hoạ, Kinh doanh phần mềm, Marketing). Gom hết vào `Others`, hay thêm nhóm `Design`, `Sales / Business`?

---

## 11. Khoá, trùng lặp, chất lượng

- `job_id = md5(source || '||' || job_url)` **[Gốc]**.
- `company_id = md5(lower(trim(company_name)))` **[Gốc]**.
- Trong một lần chạy: `dropDuplicates(["job_id"])` trước khi `MERGE` **[Gốc]**.
- Qua nhiều ngày: cùng một tin xuất hiện lại (thực tế CareerViet có 7/36 tin lặp giữa các ngày).
  **[Đề xuất]** Thêm `first_seen_date` (không bao giờ đổi), `last_seen_date` (cập nhật mỗi lần thấy),
  `row_hash` để chỉ `UPDATE` khi nội dung đổi. Từ đó biết được một tin **sống bao nhiêu ngày**.
- DLQ: thiếu `job_url`, `job_title`, `company_name` hoặc `source` → bảng DLQ, cột `error_reason`, `failed_at` **[Gốc]**.
- Sau mỗi lần chạy in `bronze_count`, `silver_count`, `drop_rate` cho từng web **[Gốc]**.

---

## 12. [Cần chốt] Một bảng Silver chung hay mỗi web một bảng

| | Gốc: `silver.<web>_jobs` (4 bảng) | Đề xuất: `silver.jobs` (1 bảng, chia theo `source`) |
|---|---|---|
| Cột | Mỗi bảng vẫn cùng bộ cột chuẩn | Một bộ cột chuẩn |
| Gold | Phải `UNION` 4 bảng | Đọc một bảng |
| Chạy lại một web | Chỉ đụng bảng web đó | `MERGE` theo `job_id`, cũng chỉ đụng dòng của web đó |

---

## 13. Lỗi đã thấy trong project gốc (sẽ có test riêng)

1. `Lên đến X` bị hiểu thành lương tối thiểu.
2. Hạn nộp `dd/mm/yyyy` bị đọc thành "còn dd ngày".
3. Nhóm nghề: điều kiện khai báo sau ghi đè điều kiện trước.
4. Đọc Bronze theo `ingested_at` (giờ chạy) thay vì `ingest_date` (ngày crawl): chạy bù sẽ lấy sai ngày.
