import logging
import os

from pyspark.sql import SparkSession

from src.utils.spark_util import CATALOG, get_spark_session

GOLD = f"{CATALOG}.gold"
TABLES = [
    "dim_company",
    "dim_location",
    "dim_job_category",
    "dim_level",
    "dim_skill",
    "fact_job_postings",
    "bridge_job_skills",
]


class GoldPublisher:
    def __init__(self, spark: SparkSession, jdbc_url: str, user: str, password: str):
        self.spark = spark
        self.jdbc_url = jdbc_url
        self.properties = {"user": user, "password": password, "driver": "org.postgresql.Driver"}
        self.logger = logging.getLogger("publish_postgres")

    def write_staging(self, table: str) -> None:
        df = self.spark.table(f"{GOLD}.{table}")
        df.write.jdbc(url=self.jdbc_url, table=f"{table}_temp", mode="overwrite", properties=self.properties)
        self.logger.info(f"Ghi {df.count()} dòng vào bảng tạm {table}_temp")

    def connect(self):
        jvm = self.spark.sparkContext._jvm
        props = jvm.java.util.Properties()
        props.setProperty("user", self.properties["user"])
        props.setProperty("password", self.properties["password"])
        return jvm.org.postgresql.Driver().connect(self.jdbc_url, props)

    def swap(self, tables: list[str]) -> None:
        conn = self.connect()
        conn.setAutoCommit(False)
        try:
            stmt = conn.createStatement()
            for table in tables:
                stmt.execute(f"DROP TABLE IF EXISTS {table}_old")
                stmt.execute(f"ALTER TABLE IF EXISTS {table} RENAME TO {table}_old")
                stmt.execute(f"ALTER TABLE {table}_temp RENAME TO {table}")
                stmt.execute(f"DROP TABLE IF EXISTS {table}_old")
            conn.commit()
            self.logger.info(f"Đã đổi {len(tables)} bảng sang bản mới trong một transaction")
        except Exception:
            conn.rollback()
            self.logger.error("Đổi bảng thất bại, giữ nguyên bản cũ cho dashboard")
            raise
        finally:
            conn.close()

    def run(self) -> None:
        self.logger.info("BẮT ĐẦU PUBLISH GOLD → POSTGRES")
        tables = []
        for table in TABLES:
            if not self.spark.catalog.tableExists(f"{GOLD}.{table}"):
                self.logger.warning(f"Chưa có bảng {GOLD}.{table}, bỏ qua")
                continue
            self.write_staging(table)
            tables.append(table)
        if not tables:
            self.logger.warning("Không có bảng Gold nào để publish")
            return
        self.swap(tables)
        self.logger.info("HOÀN TẤT PUBLISH")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    spark = get_spark_session("publish_gold_to_postgres")
    try:
        GoldPublisher(
            spark,
            jdbc_url=os.environ["SERVING_DB_URL"],
            user=os.environ["SERVING_DB_USER"],
            password=os.environ["SERVING_DB_PASSWORD"],
        ).run()
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
