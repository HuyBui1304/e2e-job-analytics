from src.utils.minio_client import get_s3

BUCKETS = ["landing", "bronze", "silver", "gold"]


def main() -> None:
    s3 = get_s3()
    existing = {b["Name"] for b in s3.list_buckets()["Buckets"]}
    for name in BUCKETS:
        if name in existing:
            print(f"Bucket {name} đã có, bỏ qua")
        else:
            s3.create_bucket(Bucket=name)
            print(f"Đã tạo bucket {name}")


if __name__ == "__main__":
    main()
