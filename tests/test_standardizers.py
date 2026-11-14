from datetime import date

import pytest
from pyspark.sql import types as T

from src.transform import standardizers as S

STR = T.StringType()


def run(spark, fn, schema, rows, *cols):
    df = spark.createDataFrame(rows, schema)
    out = fn(df).collect()
    return [tuple(r[c] for c in cols) for r in out]


def one_col(name, dtype=STR):
    return T.StructType([T.StructField(name, dtype)])


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Thoả thuận", (None, None, None, True)),
        ("Cạnh tranh", (None, None, None, True)),
        ("Very Attractive!!!", (None, None, None, True)),
        (None, (None, None, None, True)),
        ("10 - 30 triệu", (10.0, 30.0, "VND", False)),
        ("30 - 50 Triệu VND", (30.0, 50.0, "VND", False)),
        ("12tr-17tr ₫/tháng", (12.0, 17.0, "VND", False)),
        ("Tới 20 triệu", (None, 20.0, "VND", False)),
        ("Lên đến 35 Triệu VND", (None, 35.0, "VND", False)),
        ("Từ 15 triệu", (15.0, None, "VND", False)),
        ("Trên 7,5 triệu", (7.5, None, "VND", False)),
        ("15.000.000 - 20.000.000 VND", (15.0, 20.0, "VND", False)),
        ("$ 1,000-2,000 /tháng", (1000.0, 2000.0, "USD", False)),
        ("Tới $ 2,500 /tháng", (None, 2500.0, "USD", False)),
        ("$ 30tr-50tr /tháng", (30.0, 50.0, "VND", False)),
        ("850 - 1,300 USD", (850.0, 1300.0, "USD", False)),
        ("50 - 10 triệu", (None, None, None, True)),
    ],
)
def test_extract_salary(spark, raw, expected):
    got = run(spark, S.extract_salary, one_col("salary_raw"), [(raw,)],
              "salary_min", "salary_max", "salary_currency", "salary_negotiable")
    assert got == [expected]


@pytest.mark.parametrize(
    "smin, smax, currency, band",
    [
        (None, None, None, "Negotiable"),
        (10.0, 30.0, "VND", "10tr - 20tr"),
        (None, 8.0, "VND", "< 10tr"),
        (25.0, 30.0, "VND", "20tr - 30tr"),
        (1000.0, 2000.0, "USD", "> 30tr"),
    ],
)
def test_salary_band(spark, smin, smax, currency, band):
    schema = T.StructType([
        T.StructField("salary_min", T.DoubleType()),
        T.StructField("salary_max", T.DoubleType()),
        T.StructField("salary_currency", STR),
    ])
    assert run(spark, S.enrich_salary_band, schema, [(smin, smax, currency)], "salary_band") == [(band,)]


@pytest.mark.parametrize(
    "raw, months, expected",
    [
        ("2 năm", None, (2, None)),
        ("Không yêu cầu kinh nghiệm", None, (0, 0)),
        ("Trên 5 năm", None, (5, None)),
        ("3 - 5 Năm", None, (3, 5)),
        ("Lên đến 3 Năm", None, (0, 3)),
        ("3", None, (3, None)),
        (None, 37, (3, None)),
        (None, None, (None, None)),
    ],
)
def test_experience(spark, raw, months, expected):
    schema = T.StructType([T.StructField("experience_raw", STR), T.StructField("experience_months", T.IntegerType())])
    got = run(spark, S.standardize_experience, schema, [(raw, months)], "exp_min_years", "exp_max_years")
    assert got == [expected]


@pytest.mark.parametrize(
    "level, title, expected",
    [
        ("Nhân viên", "Senior Data Engineer", "Senior"),
        ("Nhân viên", "Backend Developer", "Junior"),
        ("Trưởng nhóm", "Backend Developer", "Lead"),
        ("Quản lý / Giám sát", "IT Manager", "Manager"),
        ("Mới Tốt Nghiệp", "Java Developer", "Fresher"),
        (None, "Tech Lead (Java)", "Lead"),
        (None, "Head of Data", "Manager"),
        (None, "Chief Technology Officer", "Director"),
        (None, "Thực tập sinh Data", "Intern"),
        (None, "Data Analyst", None),
    ],
)
def test_level(spark, level, title, expected):
    schema = T.StructType([T.StructField("level_raw", STR), T.StructField("job_title", STR)])
    assert run(spark, S.standardize_level, schema, [(level, title)], "level") == [(expected,)]


def test_location(spark):
    schema = one_col("locations_raw", T.ArrayType(STR))
    rows = [(["TP.HCM", " Hà Nội ", "Hồ Chí Minh"],), (None,), (["Bắc Ninh"],)]
    got = run(spark, S.standardize_location, schema, rows, "locations", "location_primary")
    assert got == [(["Hồ Chí Minh", "Hà Nội"], "Hồ Chí Minh"), ([], None), (["Bắc Ninh"], "Bắc Ninh")]


@pytest.mark.parametrize(
    "deadline, valid, expected",
    [
        ("30/11/2026", None, date(2026, 11, 30)),
        ("5/1/2027", "2027-02-01", date(2027, 1, 5)),
        (None, "2026-12-01T00:00:00+07:00", date(2026, 12, 1)),
        ("Còn 10 ngày", None, None),
    ],
)
def test_deadline(spark, deadline, valid, expected):
    schema = T.StructType([T.StructField("deadline_raw", STR), T.StructField("valid_through", STR)])
    assert run(spark, S.parse_deadline, schema, [(deadline, valid)], "deadline_date") == [(expected,)]


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Làm việc tại văn phòng / Onsite", "Onsite"),
        ("Tại văn phòng", "Onsite"),
        ("Linh hoạt", "Hybrid"),
        ("Làm từ xa", "Remote"),
        (None, None),
    ],
)
def test_working_type(spark, raw, expected):
    assert run(spark, S.standardize_working_type, one_col("working_type_raw"), [(raw,)], "working_type") == [(expected,)]


@pytest.mark.parametrize(
    "raw, expected",
    [("Đại Học trở lên", "Đại học"), ("Cao đẳng", "Cao đẳng"), ("Thạc sĩ", "Sau đại học"), (None, None)],
)
def test_education(spark, raw, expected):
    assert run(spark, S.standardize_education, one_col("education_raw"), [(raw,)], "education") == [(expected,)]


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("25-99 nhân viên", ("25-99", "Small")),
        ("51-150 nhân viên", ("51-150", "Small")),
        ("100-499 nhân viên", ("100-499", "Medium")),
        ("1.000+ nhân viên", ("1000+", "Enterprise")),
        (None, (None, None)),
    ],
)
def test_company_size(spark, raw, expected):
    got = run(spark, S.standardize_company_size, one_col("company_size_raw"), [(raw,)], "company_size", "company_size_group")
    assert got == [expected]


@pytest.mark.parametrize(
    "skills, title, expected",
    [
        (["Python", "python", " SQL ", ""], "Data Engineer (Python, Spark)", ["Python", "SQL", "Spark"]),
        ([], "C++ / C# Developer", ["C++", "C#"]),
        (None, "JavaScript Developer", ["JavaScript"]),
        (None, "Nhân viên kinh doanh", []),
    ],
)
def test_skills(spark, skills, title, expected):
    schema = T.StructType([T.StructField("skills_raw", T.ArrayType(STR)), T.StructField("job_title", STR)])
    assert run(spark, S.normalize_skills, schema, [(skills, title)], "skills") == [(expected,)]


@pytest.mark.parametrize(
    "title, expected",
    [
        ("Senior Data Engineer", "Data Engineer"),
        ("Data Engineer (Python, SQL)", "Data Engineer"),
        ("[HUB CÔNG NGHỆ TẠI HCM]_Chuyên viên Kỹ thuật dữ liệu", "Data Engineer"),
        ("Data Analyst (SQL, Power BI)", "Data Analyst"),
        ("Senior AI Expert (Machine Learning, Deep Learning, LLM)", "AI Engineer"),
        ("Backend Developer (Java)", "Backend Developer"),
        ("Kỹ Sư Lập Trình .NET (Biết Tiếng Trung)", "Backend Developer"),
        ("Salesforce Developer", "Backend Developer"),
        ("Automation Tester", "QA/QC"),
        ("DevSecOps Engineer", "Security / IT Support"),
        ("DevOps Engineer", "DevOps / SRE"),
        ("System Engineer (Embedded Automotive)", "Embedded"),
        ("Flutter Developer", "Mobile Developer"),
        ("User Acquisition (UA) Marketing (App Mobile)", "Sales / Business"),
        ("Graphic Designer", "Design"),
        ("Senior 2D Animation ( Game Industry )", "Design"),
        ("Chuyên viên Thiết kế giải pháp và quản lý kênh số", "Others"),
        ("Nhân viên kinh doanh phần mềm", "Sales / Business"),
        ("Kế toán tổng hợp", "Others"),
    ],
)
def test_job_category(spark, title, expected):
    assert run(spark, S.standardize_job_category, one_col("job_title"), [(title,)], "job_category") == [(expected,)]


def test_ids_are_stable(spark):
    schema = T.StructType([T.StructField(c, STR) for c in ("source", "job_url", "company_name")])
    rows = [("topcv", "https://a/1", "FPT Software"), ("topcv", "https://a/1", "  fpt software ")]
    got = run(spark, S.generate_ids, schema, rows, "job_id", "company_id")
    assert got[0] == got[1]
    assert len(got[0][0]) == 32
