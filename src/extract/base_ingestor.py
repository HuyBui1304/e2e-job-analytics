import json
import logging
from datetime import date
from pathlib import Path

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import StructType
from pyspark.sql.utils import AnalysisException

from src.utils.spark_util import CATALOG

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = PROJECT_ROOT / "config" / "schemas"
CORRUPT_COL = "_corrupt_record"


class BaseIngestor:
    VALID_SOURCES = ["topcv", "careerviet", "itviec", "vietnamworks"]

    def __init__(self, spark: SparkSession, source_name: str, run_date: date):
        if source_name not in self.VALID_SOURCES:
            raise ValueError(f"Source '{source_name}' không hợp lệ. Các nguồn hỗ trợ: {self.VALID_SOURCES}")

        self.spark = spark
        self.source_name = source_name
        self.run_date = run_date
        self.logger = logging.getLogger(f"ingestor.{source_name}")

        schema_json = json.loads((SCHEMA_DIR / f"{source_name}_schema.json").read_text(encoding="utf-8"))
        self.schema_fields = [f["name"] for f in schema_json["fields"]]
        schema_json["fields"].append({"name": CORRUPT_COL, "type": "string", "nullable": True, "metadata": {}})
        self.schema = StructType.fromJson(schema_json)

        day = run_date.isoformat()
        self.landing_path = f"s3a://landing/source={source_name}/ingest_date={day}/jobs.jsonl"
        self.quarantine_path = f"s3a://bronze/_quarantine/{source_name}_jobs/ingest_date={day}/"
        self.table_name = f"{CATALOG}.bronze.{source_name}_jobs"

    def detect_new_fields(self) -> list[str]:
        actual = set(self.spark.read.json(self.landing_path).columns) - {CORRUPT_COL}
        new_fields = sorted(actual - set(self.schema_fields))
        if new_fields:
            self.logger.warning(f"Phát hiện trường mới không có trong schema: {new_fields}")
        return new_fields

    def read_landing(self) -> tuple[DataFrame, DataFrame]:
        self.logger.info(f"Đọc dữ liệu từ: {self.landing_path}")
        df = (
            self.spark.read.schema(self.schema)
            .option("mode", "PERMISSIVE")
            .option("columnNameOfCorruptRecord", CORRUPT_COL)
            .json(self.landing_path)
        )
        df.cache()

        error_df = df.filter(F.col(CORRUPT_COL).isNotNull())
        valid_df = df.filter(F.col(CORRUPT_COL).isNull()).drop(CORRUPT_COL)

        total, errors = df.count(), error_df.count()
        self.logger.info(f"Tổng số dòng: {total}, hợp lệ: {total - errors}, lỗi: {errors}")
        return valid_df, error_df

    def add_audit_columns(self, df: DataFrame) -> DataFrame:
        return (
            df.withColumn("ingest_date", F.lit(self.run_date))
            .withColumn("ingested_at", F.current_timestamp())
        )

    def write_quarantine(self, error_df: DataFrame) -> None:
        if error_df.isEmpty():
            return
        self.logger.warning(f"Ghi dòng lỗi vào quarantine: {self.quarantine_path}")
        error_df.select(CORRUPT_COL).write.mode("overwrite").json(self.quarantine_path)

    def write_bronze(self, df: DataFrame) -> None:
        if df.isEmpty():
            self.logger.warning("Không có dòng hợp lệ để ghi xuống Bronze")
            return
        if self.spark.catalog.tableExists(self.table_name):
            self.logger.info(f"Ghi đè phần ingest_date={self.run_date} của bảng {self.table_name}")
            df.writeTo(self.table_name).overwritePartitions()
        else:
            self.logger.info(f"Tạo bảng mới {self.table_name}, chia theo ingest_date")
            df.writeTo(self.table_name).partitionedBy(F.col("ingest_date")).create()

    def run(self) -> None:
        self.logger.info(f"BẮT ĐẦU INGEST: source={self.source_name}, date={self.run_date}")
        try:
            self.detect_new_fields()
        except AnalysisException as e:
            if "PATH_NOT_FOUND" in str(e):
                self.logger.warning(f"Không có file landing: {self.landing_path}, bỏ qua")
                return
            raise

        valid_df, error_df = self.read_landing()
        self.write_quarantine(error_df)
        self.write_bronze(self.add_audit_columns(valid_df))

        rows = self.spark.table(self.table_name).where(F.col("ingest_date") == F.lit(self.run_date)).count()
        self.logger.info(f"HOÀN TẤT: bảng {self.table_name} có {rows} dòng cho ngày {self.run_date}")
