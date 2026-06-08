# Après on Neon Postgres

Free shared hosting for the Streamlit app without Snowflake warehouse cost.

## 1. Create Neon project

1. [console.neon.tech](https://console.neon.tech) → **New project**
2. Copy the **pooled** connection string (`postgresql://...?sslmode=require`)

Optional CLI:

```bash
npx neonctl@latest init
```

## 2. Apply schema and seed places

From project root, with `DATABASE_URL` in `.env` (or pass `--database-url`):

**From Snowflake** (if you still have dbt data there):

```bat
pip install psycopg2-binary python-dotenv snowflake-snowpark-python
python scripts/seed_neon_places.py --from-snowflake
```

**From CSV** (export `dim_places` columns once):

```bat
python scripts/seed_neon_places.py --csv data/places.csv
```

Schema only (Neon SQL Editor): paste `neon/schema.sql`.

## 3. Streamlit Cloud secrets

**Settings → Secrets** — use `streamlit/venue_swiper/.streamlit/secrets.toml.example` as template:

```toml
[app]
database_backend = "postgres"

[connections.postgresql]
url = "postgresql://..."
```

Remove the `[connections.snowflake]` block when switching fully to Neon.

**Reboot app** after saving secrets.

## 4. Local dev

```bat
cd streamlit\venue_swiper
copy .streamlit\secrets.toml.example .streamlit\secrets.toml
REM Edit secrets.toml with your Neon URL
streamlit run streamlit_app.py
```

## 5. Refresh venue catalog

Re-run seed after new fetches / `dbt run`:

```bat
python scripts/seed_neon_places.py --from-snowflake --skip-schema
```

Ratings in `venue_ratings` are preserved (upsert only touches `places`).

## Backend selection

| Environment | Auto-detect |
|-------------|-------------|
| Streamlit in Snowflake | Snowflake (active session) |
| Secrets with `[connections.postgresql]` url | Postgres |
| Secrets with `[connections.snowflake]` only | Snowflake |

Override with `[app] database_backend = "postgres"` or `"snowflake"`.
