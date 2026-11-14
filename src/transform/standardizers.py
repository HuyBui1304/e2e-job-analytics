from pyspark.sql import Column, DataFrame
from pyspark.sql import functions as F
from pyspark.sql import types as T

USD_TO_VND_MILLION = 0.025
UNICODE = "(?U)"

LOCATION_MAPPING = {
    "hồ chí minh": "Hồ Chí Minh",
    "tp hồ chí minh": "Hồ Chí Minh",
    "tp. hồ chí minh": "Hồ Chí Minh",
    "thành phố hồ chí minh": "Hồ Chí Minh",
    "hcm": "Hồ Chí Minh",
    "tp.hcm": "Hồ Chí Minh",
    "tp hcm": "Hồ Chí Minh",
    "ho chi minh": "Hồ Chí Minh",
    "ho chi minh city": "Hồ Chí Minh",
    "sài gòn": "Hồ Chí Minh",
    "saigon": "Hồ Chí Minh",
    "hà nội": "Hà Nội",
    "ha noi": "Hà Nội",
    "hanoi": "Hà Nội",
    "đà nẵng": "Đà Nẵng",
    "da nang": "Đà Nẵng",
    "hải phòng": "Hải Phòng",
    "hai phong": "Hải Phòng",
    "cần thơ": "Cần Thơ",
    "can tho": "Cần Thơ",
    "bình dương": "Bình Dương",
    "binh duong": "Bình Dương",
    "đồng nai": "Đồng Nai",
    "dong nai": "Đồng Nai",
    "nước ngoài": "Nước ngoài",
    "oversea": "Nước ngoài",
    "overseas": "Nước ngoài",
}

TITLE_LEVEL_RULES = [
    ("Director", r"\b(director|cto|cio|ciso|chief)\b|giám đốc"),
    ("Manager", r"\bhead of\b|trưởng phòng"),
    ("Lead", r"\b(lead|leader|team lead|tech lead)\b|trưởng nhóm"),
    ("Senior", r"\b(senior|sr)\b"),
    ("Middle", r"\b(middle|mid-level|mid)\b"),
    ("Junior", r"\bjunior\b"),
    ("Fresher", r"\b(fresher|graduate)\b|mới tốt nghiệp"),
    ("Intern", r"\b(intern|internship)\b|thực tập"),
]

RAW_LEVEL_RULES = [
    ("Director", r"giám đốc|director"),
    ("Manager", r"trưởng phòng|quản lý|giám sát|manager"),
    ("Lead", r"trưởng nhóm|lead"),
    ("Fresher", r"mới tốt nghiệp|fresher"),
    ("Intern", r"thực tập|intern"),
    ("Junior", r"nhân viên|chuyên viên|staff|junior"),
]

JOB_CATEGORY_RULES = [
    ("Data Engineer", r"data engineer|data warehouse|\betl\b|big data|kỹ sư dữ liệu|kỹ thuật dữ liệu|data platform|nền tảng dữ liệu|data pipeline"),
    ("Data Scientist", r"data scientist|khoa học dữ liệu"),
    ("Fullstack Developer", r"fullstack|full-stack|full stack"),
    ("AI Engineer", r"\bai\b|trí tuệ nhân tạo|\bllm\b|computer vision|\bnlp\b|genai|machine learning|deep learning|\bml\b"),
    ("Data Analyst", r"data analyst|phân tích dữ liệu|business intelligence|\bbi\b|data analysis|analytics|quản trị dữ liệu|data governance"),
    ("Business Analyst", r"business analyst|\bba\b|phân tích nghiệp vụ"),
    ("Project Manager", r"project manager|project management|quản lý dự án|scrum master|product manager|product owner|\bpo\b|\bpm\b|chuyên viên dự án|project coordinator|điều phối dự án"),
    ("Sales / Business", r"kinh doanh|\bsales?\b|business development|account manager|marketing|user acquisition"),
    ("QA/QC", r"\bqa\b|\bqc\b|tester|testing|kiểm thử|automation test|\bsdet\b|quality assurance"),
    ("Security / IT Support", r"security|devsecops|bảo mật|pentest|penetration|an toàn thông tin|an ninh (mạng|thông tin)|it support|helpdesk|help desk|hỗ trợ kỹ thuật|kỹ thuật viên"),
    ("Embedded", r"nhúng|embedded|firmware|\biot\b"),
    ("DevOps / SRE", r"devops|\bsre\b|cloud|infrastructure|hạ tầng|system admin|sysadmin|system engineer|quản trị hệ thống|kỹ thuật hệ thống|network|\bmạng\b|database administrator|\bdba\b"),
    ("Mobile Developer", r"mobile|\bios\b|android|flutter|react native|swift|kotlin"),
    ("Frontend Developer", r"frontend|front-end|front end|reactjs|\breact\b|angular|\bvue\b|web developer"),
    ("Backend Developer", r"backend|back-end|back end|\bjava\b|python|\bphp\b|nodejs|node\.js|golang|\.net|c#|ruby|rails|software engineer|developer|programmer|lập trình|kỹ sư phần mềm"),
    ("Design", r"designer|thiết kế (đồ họa|đồ hoạ|in|ui|ux|web|game)|graphic|\bui\b|\bux\b|multimedia|video|animation|\b[23]d\b"),
]

TITLE_SKILLS = [
    ("Python", r"python"), ("Java", r"java"), ("JavaScript", r"javascript"), ("TypeScript", r"typescript"),
    ("React", r"react|reactjs"), ("Angular", r"angular"), ("Vue", r"vue|vuejs"), ("NodeJS", r"nodejs|node\.js"),
    ("C++", r"c\+\+"), ("C#", r"c#"), ("PHP", r"php"), ("Golang", r"golang"), ("Kotlin", r"kotlin"),
    ("Swift", r"swift"), ("Flutter", r"flutter"), ("SQL", r"sql"), ("AWS", r"aws"), ("Azure", r"azure"),
    ("GCP", r"gcp"), ("Docker", r"docker"), ("Kubernetes", r"kubernetes|k8s"), ("Spark", r"spark"),
    ("Kafka", r"kafka"), ("Databricks", r"databricks"), ("Spring Boot", r"spring boot"), ("Linux", r"linux"),
]

def empty_str_array() -> Column:
    return F.array().cast(T.ArrayType(T.StringType()))


def first_match(text: Column, rules: list[tuple[str, str]]) -> Column:
    result = F.lit(None).cast(T.StringType())
    for value, pattern in reversed(rules):
        result = F.when(text.rlike(UNICODE + pattern), F.lit(value)).otherwise(result)
    return result


def _number(text: Column, pattern: str, group: int, usd: Column) -> Column:
    raw = F.regexp_extract(text, pattern, group)
    grouped = raw.rlike(r"^\d{1,3}([.,]\d{3})+$")
    value = (
        F.when(raw == "", F.lit(None))
        .when(grouped, F.regexp_replace(raw, r"[.,]", ""))
        .when(usd, F.regexp_replace(raw, ",", ""))
        .otherwise(F.regexp_replace(raw, ",", "."))
        .cast(T.DoubleType())
    )
    return F.when(~usd & (value >= 1000), value / 1_000_000).otherwise(value)


def extract_salary(df: DataFrame, salary_col: str = "salary_raw") -> DataFrame:
    s = F.lower(F.trim(F.col(salary_col)))
    num = r"(\d+(?:[.,]\d+)*)"
    range_pattern = num + r"\s*(?:tr|triệu)?\s*(?:usd|\$)?\s*[-–~]\s*\$?\s*" + num
    negotiable = s.isNull() | s.rlike(r"thoả thuận|thỏa thuận|thương lượng|cạnh tranh|negotiable|attractive|competitive")
    vnd = s.rlike(UNICODE + r"\d\s*tr\b|triệu|vnd|₫")
    usd = ~vnd & s.rlike(r"\$|usd")
    has_range = s.rlike(range_pattern)
    up_to = s.rlike(r"^(tới|lên đến|lên tới|up to|dưới|to)(?!\p{L})")
    from_ = s.rlike(r"^(từ|trên|from|above)(?!\p{L})")

    n1 = _number(s, num, 1, usd)
    r1 = _number(s, range_pattern, 1, usd)
    r2 = _number(s, range_pattern, 2, usd)

    smin = (
        F.when(negotiable, None)
        .when(has_range, r1)
        .when(up_to, None)
        .otherwise(n1)
    )
    smax = (
        F.when(negotiable, None)
        .when(has_range, r2)
        .when(from_, None)
        .otherwise(n1)
    )
    currency = F.when(negotiable | (smin.isNull() & smax.isNull()), None).when(usd, F.lit("USD")).otherwise(F.lit("VND"))
    floor_value = F.when(currency == "USD", F.lit(100.0)).otherwise(F.lit(1.0))
    ceiling = F.when(currency == "USD", F.lit(50000.0)).otherwise(F.lit(1000.0))
    top = F.coalesce(smax, smin)
    invalid = currency.isNotNull() & ((top < floor_value) | (top > ceiling) | (smin > smax))

    return (
        df.withColumn("salary_min", F.when(invalid, None).otherwise(smin))
        .withColumn("salary_max", F.when(invalid, None).otherwise(smax))
        .withColumn("salary_currency", F.when(invalid, None).otherwise(currency))
        .withColumn("salary_negotiable", F.col("salary_min").isNull() & F.col("salary_max").isNull())
    )


def enrich_salary_band(df: DataFrame) -> DataFrame:
    rate = F.when(F.col("salary_currency") == "USD", F.lit(USD_TO_VND_MILLION)).otherwise(F.lit(1.0))
    low = F.col("salary_min") * rate
    high = F.col("salary_max") * rate
    avg = F.when(low.isNotNull() & high.isNotNull(), (low + high) / 2).otherwise(F.coalesce(low, high))
    return df.withColumn(
        "salary_band",
        F.when(avg.isNull(), "Negotiable")
        .when(avg < 10, "< 10tr")
        .when(avg <= 20, "10tr - 20tr")
        .when(avg <= 30, "20tr - 30tr")
        .otherwise("> 30tr"),
    )


def standardize_experience(df: DataFrame, exp_col: str = "experience_raw", months_col: str = "experience_months") -> DataFrame:
    e = F.lower(F.trim(F.col(exp_col)))
    first = F.regexp_extract(e, r"(\d+)", 1)
    n1 = F.when(first == "", None).otherwise(first.cast(T.IntegerType()))
    rng = r"(\d+)\s*[-–]\s*(\d+)"
    r1 = F.regexp_extract(e, rng, 1).cast(T.IntegerType())
    r2 = F.regexp_extract(e, rng, 2).cast(T.IntegerType())
    not_required = e.rlike(r"không yêu cầu|không cần|not required|no experience|chưa có kinh nghiệm")
    up_to = e.rlike(r"^(lên đến|tới|dưới|up to|under|less than)")
    months = F.col(months_col).cast(T.DoubleType())

    exp_min = (
        F.when(not_required, 0)
        .when(e.rlike(rng), r1)
        .when(up_to & n1.isNotNull(), 0)
        .when(n1.isNotNull(), n1)
        .when(months.isNotNull(), F.floor(months / 12).cast(T.IntegerType()))
    )
    exp_max = (
        F.when(not_required, 0)
        .when(e.rlike(rng), r2)
        .when(up_to, n1)
    )
    return df.withColumn("exp_min_years", exp_min.cast(T.IntegerType())).withColumn(
        "exp_max_years", exp_max.cast(T.IntegerType())
    )


def standardize_level(df: DataFrame, level_col: str = "level_raw", title_col: str = "job_title") -> DataFrame:
    from_title = first_match(F.lower(F.col(title_col)), TITLE_LEVEL_RULES)
    from_raw = first_match(F.lower(F.trim(F.col(level_col))), RAW_LEVEL_RULES)
    return df.withColumn("level", F.coalesce(from_title, from_raw))


def standardize_location(df: DataFrame, locations_col: str = "locations_raw") -> DataFrame:
    mapping = F.create_map(*[F.lit(x) for kv in LOCATION_MAPPING.items() for x in kv])
    cleaned = F.transform(
        F.coalesce(F.col(locations_col), empty_str_array()),
        lambda x: F.coalesce(F.element_at(mapping, F.lower(F.trim(x))), F.trim(x)),
    )
    cleaned = F.array_distinct(F.filter(cleaned, lambda x: x.isNotNull() & (x != "")))
    return df.withColumn("locations", cleaned).withColumn("location_primary", F.element_at(F.col("locations"), 1))


def parse_deadline(df: DataFrame, deadline_col: str = "deadline_raw", fallback_col: str = "valid_through") -> DataFrame:
    raw = F.trim(F.col(deadline_col))
    dmy = F.when(raw.rlike(r"^\d{1,2}/\d{1,2}/\d{4}$"), F.to_date(raw, "d/M/yyyy"))
    iso = F.when(raw.rlike(r"^\d{4}-\d{2}-\d{2}"), F.to_date(F.substring(raw, 1, 10)))
    fallback = F.trim(F.col(fallback_col))
    fallback_date = F.when(fallback.rlike(r"^\d{4}-\d{2}-\d{2}"), F.to_date(F.substring(fallback, 1, 10)))
    return df.withColumn("deadline_date", F.coalesce(dmy, iso, fallback_date))


def parse_date_posted(df: DataFrame, col: str = "date_posted_raw") -> DataFrame:
    raw = F.trim(F.col(col))
    return df.withColumn("date_posted", F.when(raw.rlike(r"^\d{4}-\d{2}-\d{2}"), F.to_date(F.substring(raw, 1, 10))))


def standardize_working_type(df: DataFrame, wt_col: str = "working_type_raw") -> DataFrame:
    w = F.lower(F.col(wt_col))
    remote = w.rlike(r"remote|từ xa")
    office = w.rlike(r"văn phòng|onsite|office")
    return df.withColumn(
        "working_type",
        F.when(w.rlike(r"hybrid|linh hoạt|kết hợp") | (remote & office), "Hybrid")
        .when(remote, "Remote")
        .when(office, "Onsite"),
    )


def standardize_education(df: DataFrame, edu_col: str = "education_raw") -> DataFrame:
    e = F.lower(F.col(edu_col))
    return df.withColumn(
        "education",
        F.when(e.rlike(r"thạc sĩ|tiến sĩ|sau đại học"), "Sau đại học")
        .when(e.rlike(r"đại học|cử nhân|kỹ sư"), "Đại học")
        .when(e.rlike(r"cao đẳng"), "Cao đẳng")
        .when(e.rlike(r"trung cấp"), "Trung cấp")
        .when(e.rlike(r"không yêu cầu"), "Không yêu cầu"),
    )


def standardize_company_size(df: DataFrame, size_col: str = "company_size_raw") -> DataFrame:
    cleaned = F.regexp_replace(F.col(size_col), r"[.,\s]", "")
    plus = F.regexp_extract(cleaned, r"(\d+\+)", 1)
    span = F.regexp_extract(cleaned, r"(\d+[-–]\d+)", 1)
    lower = F.regexp_extract(cleaned, r"(\d+)", 1)
    lower_n = F.when(lower == "", None).otherwise(lower.cast(T.IntegerType()))
    return df.withColumn(
        "company_size",
        F.when(plus != "", plus).when(span != "", F.regexp_replace(span, "–", "-")),
    ).withColumn(
        "company_size_group",
        F.when(lower_n.isNull(), None)
        .when(lower_n < 100, "Small")
        .when(lower_n < 500, "Medium")
        .when(lower_n < 1000, "Large")
        .otherwise("Enterprise"),
    )


def normalize_skills(df: DataFrame, skills_col: str = "skills_raw", title_col: str = "job_title") -> DataFrame:
    title = F.lower(F.col(title_col))
    from_title = F.filter(
        F.array(*[F.when(title.rlike(rf"(?<![a-z0-9]){p}(?![a-z0-9])"), F.lit(name)) for name, p in TITLE_SKILLS]),
        lambda x: x.isNotNull(),
    )
    merged = F.concat(F.coalesce(F.col(skills_col), empty_str_array()), from_title)
    trimmed = F.filter(F.transform(merged, lambda x: F.trim(x)), lambda x: x.isNotNull() & (x != ""))
    df = df.withColumn("skills", trimmed)
    return df.withColumn(
        "skills",
        F.expr("filter(skills, (x, i) -> array_position(transform(skills, y -> lower(y)), lower(x)) = i + 1)"),
    )


def standardize_job_category(df: DataFrame, title_col: str = "job_title") -> DataFrame:
    return df.withColumn(
        "job_category",
        F.coalesce(first_match(F.lower(F.col(title_col)), JOB_CATEGORY_RULES), F.lit("Others")),
    )


def generate_ids(df: DataFrame) -> DataFrame:
    return df.withColumn("job_id", F.md5(F.concat_ws("||", F.col("source"), F.col("job_url")))).withColumn(
        "company_id", F.md5(F.lower(F.trim(F.col("company_name"))))
    )
