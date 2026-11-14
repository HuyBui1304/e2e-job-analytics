import logging
from datetime import date

from pyspark.sql import Column, DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql import types as T

from src.transform import standardizers as S
from src.utils.spark_util import CATALOG

VALID_SOURCES = ["topcv", "careerviet", "itviec", "vietnamworks"]
SILVER_TABLE = f"{CATALOG}.silver.jobs"
DLQ_TABLE = f"{CATALOG}.silver.jobs_dlq"
REQUIRED_COLUMNS = ["source", "job_url", "job_title", "company_name"]

COMMON_COLUMNS = {
    "source_job_id": "job_id",
    "job_url": "job_url",
    "job_title": "job_title",
    "company_name": "company_name",
    "company_url": "company_url",
    "locations_raw": "location_regions",
    "valid_through": "valid_through",
    "date_posted_raw": "date_posted",
    "description": "description",
    "requirements": "requirements",
    "ingest_date": "ingest_date",
    "ingested_at": "ingested_at",
}

SOURCE_COLUMNS = {
    "topcv": {
        "company_industry": "company_field",
        "company_size_raw": "company_size",
        "salary_raw": "salary",
        "experience_raw": "experience",
        "experience_months": "experience_months",
        "level_raw": "level",
        "education_raw": "education",
        "working_type_raw": "working_type",
        "deadline_raw": "deadline",
    },
    "careerviet": {
        "company_industry": "industry",
        "salary_raw": "salary",
        "experience_raw": "experience",
        "experience_months": "experience_months",
        "level_raw": "level",
        "education_raw": "education",
        "deadline_raw": "deadline",
    },
    "itviec": {
        "company_industry": "company_industry",
        "company_size_raw": "company_size",
        "salary_raw": ["salary_value", "salary"],
        "experience_months": "experience_months",
        "working_type_raw": "working_type",
    },
    "vietnamworks": {
        "company_industry": "job_industry",
        "salary_raw": "salary",
        "experience_raw": "experience",
        "level_raw": "level",
        "education_raw": "education",
        "working_type_raw": "working_type",
    },
}

SKILL_COLUMNS = {
    "topcv": ["skills", "skills_required", "skills_preferred"],
    "careerviet": ["skills", "job_tags"],
    "itviec": ["skills", "skills_tags"],
    "vietnamworks": ["skills", "skills_tags"],
}

STRING_RAW_COLUMNS = [
    "company_industry", "company_size_raw", "salary_raw", "experience_raw", "experience_months",
    "level_raw", "education_raw", "working_type_raw", "deadline_raw",
]

BUSINESS_COLUMNS = [
    "source_job_id", "job_url", "job_title", "job_category", "level",
    "company_id", "company_name", "company_url", "company_industry", "company_size", "company_size_group",
    "locations", "location_primary", "working_type", "education", "exp_min_years", "exp_max_years",
    "salary_raw", "salary_min", "salary_max", "salary_currency", "salary_negotiable", "salary_band",
    "skills", "deadline_date", "date_posted", "description", "requirements",
]

SILVER_COLUMNS = ["job_id", "source", *BUSINESS_COLUMNS, "row_hash", "first_seen_date", "last_seen_date", "updated_at"]

DLQ_COLUMNS = ["source", "source_job_id", "job_url", "job_title", "company_name", "error_reason", "ingest_date", "failed_at"]


def blank(col: str) -> Column:
    return F.col(col).isNull() | (F.trim(F.col(col)) == "")


class JobStandardizer:
    def __init__(self, spark: SparkSession, source_name: str, run_date: date):
        if source_name not in VALID_SOURCES:
            raise ValueError(f"Source '{source_name}' không hợp lệ. Các nguồn hỗ trợ: {VALID_SOURCES}")
        self.spark = spark
        self.source_name = source_name
        self.run_date = run_date
        self.bronze_table = f"{CATALOG}.bronze.{source_name}_jobs"
        self.logger = logging.getLogger(f"standardizer.{source_name}")

    def read_bronze(self) -> DataFrame | None:
        if not self.spark.catalog.tableExists(self.bronze_table):
            self.logger.warning(f"Chưa có bảng {self.bronze_table}, bỏ qua")
            return None
        df = self.spark.table(self.bronze_table).where(F.col("ingest_date") == F.lit(self.run_date))
        return df

    def map_columns(self, df: DataFrame) -> DataFrame:
        available = set(df.columns)

        def pick(name: str | list[str] | None) -> Column:
            names = [name] if isinstance(name, str) else (name or [])
            cols = [F.col(n) for n in names if n in available]
            if not cols:
                return F.lit(None).cast(T.StringType())
            return F.coalesce(*cols) if len(cols) > 1 else cols[0]

        mapping = SOURCE_COLUMNS[self.source_name]
        skills = [F.coalesce(F.col(c), S.empty_str_array()) for c in SKILL_COLUMNS[self.source_name] if c in available]

        return df.select(
            F.lit(self.source_name).alias("source"),
            *[pick(bronze).alias(silver) for silver, bronze in COMMON_COLUMNS.items()],
            *[pick(mapping.get(name)).cast(T.StringType()).alias(name) for name in STRING_RAW_COLUMNS],
            (F.concat(*skills) if skills else S.empty_str_array()).alias("skills_raw"),
        )

    def split_invalid(self, df: DataFrame) -> tuple[DataFrame, DataFrame]:
        reason = F.concat_ws(", ", *[F.when(blank(c), F.lit(f"missing {c}")) for c in REQUIRED_COLUMNS])
        df = df.withColumn("error_reason", F.when(reason != "", reason))
        valid = df.where(F.col("error_reason").isNull()).drop("error_reason")
        invalid = df.where(F.col("error_reason").isNotNull()).withColumn("failed_at", F.current_timestamp())
        return valid, invalid.select(*DLQ_COLUMNS)

    def standardize(self, df: DataFrame) -> DataFrame:
        return (
            df.withColumn("job_title", F.trim(F.col("job_title")))
            .withColumn("company_name", F.trim(F.col("company_name")))
            .transform(S.extract_salary)
            .transform(S.enrich_salary_band)
            .transform(S.standardize_experience)
            .transform(S.standardize_level)
            .transform(S.standardize_location)
            .transform(S.parse_deadline)
            .transform(S.parse_date_posted)
            .transform(S.standardize_working_type)
            .transform(S.standardize_education)
            .transform(S.standardize_company_size)
            .transform(S.normalize_skills)
            .transform(S.standardize_job_category)
            .transform(S.generate_ids)
        )

    def add_tracking_columns(self, df: DataFrame) -> DataFrame:
        payload = F.to_json(F.struct(*[F.col(c) for c in BUSINESS_COLUMNS]))
        return (
            df.withColumn("row_hash", F.sha2(payload, 256))
            .withColumn("first_seen_date", F.lit(self.run_date))
            .withColumn("last_seen_date", F.lit(self.run_date))
            .withColumn("updated_at", F.current_timestamp())
            .select(*SILVER_COLUMNS)
        )

    def write_dlq(self, dlq_df: DataFrame) -> None:
        if self.spark.catalog.tableExists(DLQ_TABLE):
            self.spark.sql(
                f"DELETE FROM {DLQ_TABLE} WHERE source = '{self.source_name}' AND ingest_date = DATE '{self.run_date}'"
            )
        if dlq_df.isEmpty():
            return
        self.logger.warning(f"Ghi {dlq_df.count()} dòng lỗi vào {DLQ_TABLE}")
        if self.spark.catalog.tableExists(DLQ_TABLE):
            dlq_df.writeTo(DLQ_TABLE).append()
        else:
            dlq_df.writeTo(DLQ_TABLE).partitionedBy(F.col("ingest_date")).create()

    def write_silver(self, df: DataFrame) -> None:
        if not self.spark.catalog.tableExists(SILVER_TABLE):
            self.logger.info(f"Tạo bảng mới {SILVER_TABLE}, chia theo source")
            df.writeTo(SILVER_TABLE).partitionedBy(F.col("source")).create()
            return

        df.createOrReplaceTempView("silver_updates")
        business_set = ",\n                ".join(f"t.{c} = s.{c}" for c in BUSINESS_COLUMNS)
        self.logger.info(f"MERGE vào {SILVER_TABLE} theo job_id")
        self.spark.sql(f"""
            MERGE INTO {SILVER_TABLE} t
            USING silver_updates s
            ON t.job_id = s.job_id
            WHEN MATCHED AND t.row_hash <> s.row_hash AND s.last_seen_date >= t.last_seen_date THEN UPDATE SET
                {business_set},
                t.row_hash = s.row_hash,
                t.updated_at = s.updated_at,
                t.first_seen_date = least(t.first_seen_date, s.first_seen_date),
                t.last_seen_date = greatest(t.last_seen_date, s.last_seen_date)
            WHEN MATCHED AND (s.first_seen_date < t.first_seen_date OR s.last_seen_date > t.last_seen_date) THEN UPDATE SET
                t.first_seen_date = least(t.first_seen_date, s.first_seen_date),
                t.last_seen_date = greatest(t.last_seen_date, s.last_seen_date)
            WHEN NOT MATCHED THEN INSERT *
        """)

    def log_quality(self, bronze_count: int, silver_df: DataFrame, dlq_count: int) -> None:
        silver_count = silver_df.count()
        dropped = bronze_count - silver_count
        drop_rate = dropped / bronze_count if bronze_count else 0.0
        self.logger.info(
            f"Bronze: {bronze_count}, Silver: {silver_count}, DLQ: {dlq_count}, "
            f"trùng/bỏ: {dropped - dlq_count}, drop_rate: {drop_rate:.1%}"
        )
        checks = {
            "salary_min/max": F.col("salary_min").isNotNull() | F.col("salary_max").isNotNull(),
            "level": F.col("level").isNotNull(),
            "exp_min_years": F.col("exp_min_years").isNotNull(),
            "locations": F.size("locations") > 0,
            "deadline_date": F.col("deadline_date").isNotNull(),
            "working_type": F.col("working_type").isNotNull(),
            "skills": F.size("skills") > 0,
            "job_category != Others": F.col("job_category") != "Others",
        }
        row = silver_df.select(*[F.sum(c.cast("int")).alias(name) for name, c in checks.items()]).first()
        for name in checks:
            self.logger.info(f"  {name:<24} {row[name] or 0}/{silver_count}")

    def run(self) -> None:
        self.logger.info(f"BẮT ĐẦU CHUẨN HÓA: source={self.source_name}, date={self.run_date}")
        bronze_df = self.read_bronze()
        if bronze_df is None:
            return
        bronze_count = bronze_df.count()
        if bronze_count == 0:
            self.logger.warning(f"Bronze không có dòng nào cho ngày {self.run_date}, bỏ qua")
            return

        valid_df, dlq_df = self.split_invalid(self.map_columns(bronze_df))
        silver_df = self.add_tracking_columns(self.standardize(valid_df).dropDuplicates(["job_id"])).cache()

        self.write_dlq(dlq_df)
        self.log_quality(bronze_count, silver_df, dlq_df.count())
        self.write_silver(silver_df)
        silver_df.unpersist()

        rows = self.spark.table(SILVER_TABLE).where(F.col("source") == self.source_name).count()
        self.logger.info(f"HOÀN TẤT: {SILVER_TABLE} có {rows} dòng của {self.source_name}")
