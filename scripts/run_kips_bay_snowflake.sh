#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
python fetch_manhattan_places.py --kips-bay --snowflake
echo ""
echo "Next: cd dbt && dbt run"
