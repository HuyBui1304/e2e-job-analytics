import argparse
import logging
from datetime import date

from src.extract.base_ingestor import BaseIngestor
from src.utils.spark_util import get_spark_session


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest dữ liệu từ landing lên Bronze")
    parser.add_argument("--source", required=True, choices=BaseIngestor.VALID_SOURCES + ["all"])
    parser.add_argument("--date", type=date.fromisoformat, default=date.today())
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    sources = BaseIngestor.VALID_SOURCES if args.source == "all" else [args.source]

    spark = get_spark_session("ingest_landing_to_bronze")
    try:
        for source in sources:
            BaseIngestor(spark, source, args.date).run()
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
