#!/usr/bin/env python3
"""Apply neon/schema.sql and load places from Snowflake dim_places or a CSV export."""

from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None  # type: ignore[misc, assignment]

PLACE_COLUMNS = (
    "google_place_id",
    "place_name",
    "formatted_address",
    "short_formatted_address",
    "latitude",
    "longitude",
    "primary_type",
    "venue_category",
    "price_level",
    "website_uri",
    "borough",
)


def load_database_url(explicit: str | None) -> str:
    if explicit:
        return explicit
    if load_dotenv:
        load_dotenv(ROOT / ".env")
    url = os.environ.get("DATABASE_URL") or os.environ.get("NEON_DATABASE_URL")
    if not url:
        raise SystemExit(
            "Set DATABASE_URL (Neon pooled connection string) or pass --database-url"
        )
    return url


def apply_schema(conn) -> None:
    schema_path = ROOT / "neon" / "schema.sql"
    sql = schema_path.read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()
    print(f"Applied schema from {schema_path}")


def rows_from_csv(path: Path) -> list[dict[str, str | float | None]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = []
        for row in reader:
            rows.append({col: row.get(col) or row.get(col.upper()) for col in PLACE_COLUMNS})
        return rows


def rows_from_snowflake() -> list[dict[str, str | float | None]]:
    if load_dotenv:
        load_dotenv(ROOT / ".env")

    from snowflake.snowpark import Session

    configs = {
        "account": os.environ["SNOWFLAKE_ACCOUNT"],
        "user": os.environ["SNOWFLAKE_USER"],
        "password": os.environ["SNOWFLAKE_PASSWORD"],
        "role": os.environ.get("SNOWFLAKE_ROLE", ""),
        "warehouse": os.environ["SNOWFLAKE_WAREHOUSE"],
        "database": os.environ.get("SNOWFLAKE_DATABASE", "VENUE_HYPE"),
        "schema": os.environ.get("SNOWFLAKE_SCHEMA", "RAW"),
    }
    configs = {k: v for k, v in configs.items() if v}

    session = Session.builder.configs(configs).create()
    sql = """
        select
            google_place_id,
            place_name,
            formatted_address,
            short_formatted_address,
            latitude,
            longitude,
            primary_type,
            venue_category,
            price_level,
            website_uri,
            borough
        from venue_hype.staging_marts.dim_places
    """
    result = session.sql(sql).collect()
    rows = []
    for row in result:
        data = row.as_dict()
        rows.append({col.lower(): data.get(col.upper()) or data.get(col) for col in PLACE_COLUMNS})
    return rows


def upsert_places(conn, rows: list[dict[str, str | float | None]]) -> None:
    if not rows:
        print("No rows to load.")
        return

    sql = """
        insert into places (
            google_place_id, place_name, formatted_address, short_formatted_address,
            latitude, longitude, primary_type, venue_category, price_level,
            website_uri, borough
        ) values (
            %(google_place_id)s, %(place_name)s, %(formatted_address)s,
            %(short_formatted_address)s, %(latitude)s, %(longitude)s,
            %(primary_type)s, %(venue_category)s, %(price_level)s,
            %(website_uri)s, %(borough)s
        )
        on conflict (google_place_id) do update set
            place_name = excluded.place_name,
            formatted_address = excluded.formatted_address,
            short_formatted_address = excluded.short_formatted_address,
            latitude = excluded.latitude,
            longitude = excluded.longitude,
            primary_type = excluded.primary_type,
            venue_category = excluded.venue_category,
            price_level = excluded.price_level,
            website_uri = excluded.website_uri,
            borough = excluded.borough
    """
    with conn.cursor() as cur:
        cur.executemany(sql, rows)
    conn.commit()
    print(f"Upserted {len(rows)} places.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed Neon places table for Après")
    parser.add_argument("--database-url", help="Neon Postgres URL (or set DATABASE_URL)")
    parser.add_argument("--csv", type=Path, help="CSV export with place columns")
    parser.add_argument(
        "--from-snowflake",
        action="store_true",
        help="Load from VENUE_HYPE.STAGING_MARTS.DIM_PLACES using SNOWFLAKE_* env",
    )
    parser.add_argument("--skip-schema", action="store_true", help="Skip applying neon/schema.sql")
    args = parser.parse_args()

    if not args.csv and not args.from_snowflake:
        parser.error("Provide --csv path or --from-snowflake")

    import psycopg2

    url = load_database_url(args.database_url)
    conn = psycopg2.connect(url)

    try:
        if not args.skip_schema:
            apply_schema(conn)

        if args.from_snowflake:
            rows = rows_from_snowflake()
        else:
            rows = rows_from_csv(args.csv)

        upsert_places(conn, rows)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
