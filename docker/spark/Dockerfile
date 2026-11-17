FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Ho_Chi_Minh

RUN apt-get update \
    && apt-get install -y --no-install-recommends openjdk-17-jre-headless procps tzdata \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH" \
    PYSPARK_PYTHON=/app/.venv/bin/python \
    PYTHONPATH=/app

COPY src/__init__.py ./src/__init__.py
COPY src/utils/ ./src/utils/
RUN python -c "from pyspark.sql import SparkSession; from src.utils.spark_util import PACKAGES; SparkSession.builder.master('local[1]').config('spark.jars.packages', ','.join(PACKAGES)).getOrCreate().stop()"

COPY src/ ./src/
COPY config/ ./config/
