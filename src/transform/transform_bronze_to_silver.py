import argparse
import logging
from datetime import date

from src.transform.job_standardizer import VALID_SOURCES, JobStandardizer
from src.utils.spark_util import get_spark_session


def main() -> None:
    parser = argparse.ArgumentParser(description="Chuẩn hóa dữ liệu từ Bronze lên Silver")
    parser.add_argument("--source", required=True, choices=VALID_SOURCES + ["all"])
    parser.add_argument("--date", type=date.fromisoformat, default=date.today())
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    sources = VALID_SOURCES if args.source == "all" else [args.source]

    spark = get_spark_session("transform_bronze_to_silver")
    try:
        for source in sources:
            JobStandardizer(spark, source, args.date).run()
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
