from src.utils.spark_util import CATALOG, get_spark_session

NAMESPACES = ["bronze", "silver", "gold"]


def main() -> None:
    spark = get_spark_session("init_namespace")
    for name in NAMESPACES:
        spark.sql(f"CREATE NAMESPACE IF NOT EXISTS {CATALOG}.{name} LOCATION 's3a://{name}/'")
        print(f"Namespace {CATALOG}.{name} -> s3a://{name}/")
    spark.sql(f"SHOW NAMESPACES IN {CATALOG}").show()
    spark.stop()


if __name__ == "__main__":
    main()
