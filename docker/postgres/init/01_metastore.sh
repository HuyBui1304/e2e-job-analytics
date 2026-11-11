#!/bin/bash
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE ROLE hive LOGIN PASSWORD '${HIVE_DB_PASSWORD}';
    CREATE DATABASE metastore_db OWNER hive;
EOSQL
