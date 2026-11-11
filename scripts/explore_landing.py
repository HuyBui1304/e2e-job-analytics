import json
import sys
from pathlib import Path

from pyspark.sql import functions as F
from pyspark.sql.types import StructType

from src.utils.spark_util import get_spark_session


def load_schema(source: str) -> StructType:
    schema_json = json.loads(Path(f"config/schemas/{source}_schema.json").read_text(encoding="utf-8"))
    schema_json["fields"].append({"name": "_corrupt_record", "type": "string", "nullable": True, "metadata": {}})
    return StructType.fromJson(schema_json)


def main() -> None:
    source, run_date = sys.argv[1], sys.argv[2]
    path = f"s3a://landing/source={source}/ingest_date={run_date}/jobs.jsonl"

    spark = get_spark_session(f"explore_{source}")
    df = (
        spark.read.schema(load_schema(source))
        .option("mode", "PERMISSIVE")
        .option("columnNameOfCorruptRecord", "_corrupt_record")
        .json(path)
    )
    df.cache()

    print(f"\nĐọc: {path}")
    df.printSchema()
    print("Tổng số dòng:", df.count())
    print("Dòng hỏng:", df.filter(F.col("_corrupt_record").isNotNull()).count())

    col = "level" if "level" in df.columns else "working_type"
    print(f"\n[DataFrame] Số tin theo {col}")
    df.groupBy(col).count().orderBy(F.desc("count")).show(truncate=False)

    df.createOrReplaceTempView("jobs")
    print("[SQL] Cùng câu đó viết bằng SQL")
    spark.sql(f"SELECT {col}, COUNT(*) AS count FROM jobs GROUP BY {col} ORDER BY count DESC").show(truncate=False)

    print("[SQL] Mỗi kỹ năng xuất hiện ở bao nhiêu tin")
    spark.sql("""
        SELECT skill, COUNT(*) AS so_tin
        FROM jobs
        LATERAL VIEW explode(skills) t AS skill
        GROUP BY skill
        ORDER BY so_tin DESC
    """).show(10, truncate=False)

    input("Mở http://localhost:4040 để xem Spark UI, xong bấm Enter để tắt Spark...")
    spark.stop()


if __name__ == "__main__":
    main()
