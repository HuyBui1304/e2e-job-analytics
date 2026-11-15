import argparse
import logging
from datetime import date

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from src.transform.job_standardizer import SILVER_TABLE
from src.transform.standardizers import USD_TO_VND_MILLION
from src.utils.spark_util import CATALOG, get_spark_session

GOLD = f"{CATALOG}.gold"
FACT_TABLE = f"{GOLD}.fact_job_postings"
BRIDGE_TABLE = f"{GOLD}.bridge_job_skills"

FACT_COLUMNS = [
    "job_id", "source", "source_job_id", "job_url", "job_title",
    "company_id", "location_id", "job_category_id", "level_id",
    "working_type", "education", "exp_min_years", "exp_max_years",
    "salary_min", "salary_max", "salary_currency", "salary_negotiable", "salary_band",
    "salary_min_vnd", "salary_max_vnd",
    "deadline_date", "date_posted", "first_seen_date", "last_seen_date", "updated_at",
]


def name_id(col: str) -> F.Column:
    return F.md5(F.lower(F.trim(F.col(col))))


class GoldTransformer:
    def __init__(self, spark: SparkSession, run_date: date):
        self.spark = spark
        self.run_date = run_date
        self.logger = logging.getLogger("gold_transformer")

    def read_silver(self) -> DataFrame | None:
        if not self.spark.catalog.tableExists(SILVER_TABLE):
            self.logger.warning(f"Chưa có bảng {SILVER_TABLE}")
            return None
        df = self.spark.table(SILVER_TABLE).where(F.col("last_seen_date") == F.lit(self.run_date))
        if df.isEmpty():
            self.logger.warning(f"Silver không có tin nào thấy trong ngày {self.run_date}")
            return None
        return df

    def merge_dimension(self, dim_df: DataFrame, name: str, pk: str) -> None:
        table = f"{GOLD}.{name}"
        if not self.spark.catalog.tableExists(table):
            dim_df.writeTo(table).tableProperty("format-version", "2").create()
        else:
            dim_df.createOrReplaceTempView(f"updates_{name}")
            update_set = ", ".join(f"t.{c} = s.{c}" for c in dim_df.columns if c != pk)
            self.spark.sql(f"""
                MERGE INTO {table} t
                USING updates_{name} s
                ON t.{pk} = s.{pk}
                WHEN MATCHED THEN UPDATE SET {update_set}
                WHEN NOT MATCHED THEN INSERT *
            """)
        self.logger.info(f"{table}: {self.spark.table(table).count()} dòng")

    def name_dimension(self, df: DataFrame, col: str, name: str, prefix: str) -> None:
        dim = (
            df.where(F.col(col).isNotNull() & (F.trim(F.col(col)) != ""))
            .groupBy(name_id(col).alias(f"{prefix}_id"))
            .agg(F.min(F.trim(F.col(col))).alias(f"{prefix}_name"))
        )
        self.merge_dimension(dim, name, f"{prefix}_id")

    def process_dimensions(self, df: DataFrame) -> None:
        company = (
            df.where(F.col("company_id").isNotNull())
            .select("company_id", "company_name", "company_industry", "company_size",
                    "company_size_group", "company_url")
            .dropDuplicates(["company_id"])
        )
        self.merge_dimension(company, "dim_company", "company_id")
        self.name_dimension(df, "location_primary", "dim_location", "location")
        self.name_dimension(df, "job_category", "dim_job_category", "job_category")
        self.name_dimension(df, "level", "dim_level", "level")
        skills = df.select(F.explode("skills").alias("skill"))
        self.name_dimension(skills, "skill", "dim_skill", "skill")

    def build_fact(self, df: DataFrame) -> DataFrame:
        rate = F.when(F.col("salary_currency") == "USD", F.lit(USD_TO_VND_MILLION)).otherwise(F.lit(1.0))
        return (
            df.withColumn("location_id", name_id("location_primary"))
            .withColumn("job_category_id", name_id("job_category"))
            .withColumn("level_id", name_id("level"))
            .withColumn("salary_min_vnd", F.round(F.col("salary_min") * rate, 2))
            .withColumn("salary_max_vnd", F.round(F.col("salary_max") * rate, 2))
            .select(*FACT_COLUMNS)
        )

    def write_fact(self, fact: DataFrame) -> None:
        if not self.spark.catalog.tableExists(FACT_TABLE):
            (fact.writeTo(FACT_TABLE).tableProperty("format-version", "2")
             .partitionedBy(F.col("first_seen_date")).create())
        else:
            fact.createOrReplaceTempView("updates_fact")
            update_set = ", ".join(
                f"t.{c} = COALESCE(s.{c}, t.{c})" for c in FACT_COLUMNS if c not in ("job_id", "first_seen_date")
            )
            self.spark.sql(f"""
                MERGE INTO {FACT_TABLE} t
                USING updates_fact s
                ON t.job_id = s.job_id
                WHEN MATCHED THEN UPDATE SET {update_set}
                WHEN NOT MATCHED THEN INSERT *
            """)
        self.logger.info(f"{FACT_TABLE}: {self.spark.table(FACT_TABLE).count()} dòng")

    def write_bridge(self, df: DataFrame) -> None:
        bridge = (
            df.select("job_id", F.explode("skills").alias("skill"))
            .where(F.trim(F.col("skill")) != "")
            .select("job_id", name_id("skill").alias("skill_id"))
            .dropDuplicates()
            .withColumn("bridge_id", F.md5(F.concat_ws("||", "job_id", "skill_id")))
        )
        if not self.spark.catalog.tableExists(BRIDGE_TABLE):
            bridge.writeTo(BRIDGE_TABLE).tableProperty("format-version", "2").create()
        else:
            df.select("job_id").distinct().createOrReplaceTempView("batch_jobs")
            bridge.createOrReplaceTempView("updates_bridge")
            self.spark.sql(f"DELETE FROM {BRIDGE_TABLE} WHERE job_id IN (SELECT job_id FROM batch_jobs)")
            self.spark.sql(f"INSERT INTO {BRIDGE_TABLE} SELECT * FROM updates_bridge")
        self.logger.info(f"{BRIDGE_TABLE}: {self.spark.table(BRIDGE_TABLE).count()} dòng")

    def run(self) -> None:
        self.logger.info(f"BẮT ĐẦU GOLD: date={self.run_date}")
        df = self.read_silver()
        if df is None:
            return
        df = df.cache()
        self.logger.info(f"Đọc {df.count()} tin từ Silver")
        self.process_dimensions(df)
        self.write_fact(self.build_fact(df))
        self.write_bridge(df)
        df.unpersist()
        self.logger.info("HOÀN TẤT GOLD")


def main() -> None:
    parser = argparse.ArgumentParser(description="Dựng star schema Gold từ Silver")
    parser.add_argument("--date", type=date.fromisoformat, default=date.today())
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    spark = get_spark_session("transform_silver_to_gold")
    try:
        GoldTransformer(spark, args.date).run()
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
