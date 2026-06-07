#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONN="${SNOWSQL_CONNECTION:-venue_hype}"
echo "Bootstrapping VENUE_HYPE via snowsql connection: $CONN"
snowsql -c "$CONN" -f "$ROOT/snowflake/setup.sql"
