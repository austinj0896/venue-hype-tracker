"""
Fetch nightlife-oriented places via Places API (New) Nearby Search.

Loads into SQLite (default) or Snowflake (--snowflake).

Usage (from venue_hype_tracker directory):
  python fetch_manhattan_places.py --manhattan-beach --snowflake
  python fetch_manhattan_places.py --manhattan-beach --snowflake --dense
  python fetch_manhattan_places.py --murray-hill --snowflake --lat-steps 3 --lon-steps 3 --radius-m 550
"""

from __future__ import annotations

import argparse
import sys
import time

from config import google_places_api_key, project_root, sqlite_path
from database import connect, init_schema, upsert_place as sqlite_upsert_place, utc_now_iso
from places_api import (
    AREA_PRESETS,
    DEFAULT_INCLUDED_TYPES,
    MANHATTAN_BOUNDS,
    AreaPreset,
    iter_grid,
    nearby_search,
    parse_place_row,
)
from snowflake_store import (
    finish_fetch_run,
    snowflake_connection,
    snowflake_target_label,
    start_fetch_run,
    upsert_place as snowflake_upsert_place,
    utc_now_iso as snowflake_utc_now_iso,
)

PRESET_FLAG_NAMES = ("kips_bay", "murray_hill", "manhattan_beach")

DEFAULT_MANHATTAN_LAT_STEPS = 8
DEFAULT_MANHATTAN_LON_STEPS = 5
DEFAULT_MANHATTAN_RADIUS_M = 950.0
DEFAULT_DENSE_MANHATTAN_LAT_STEPS = 12
DEFAULT_DENSE_MANHATTAN_LON_STEPS = 10
DEFAULT_DENSE_MANHATTAN_RADIUS_M = 700.0


def resolve_grid_params(
    args: argparse.Namespace,
    preset: AreaPreset | None,
) -> tuple[int, int, float]:
    """CLI grid flags override preset defaults; --dense applies preset dense grid when no overrides."""
    if preset:
        base_lat, base_lon, base_radius = preset.grid(dense=args.dense)
        return (
            args.lat_steps if args.lat_steps is not None else base_lat,
            args.lon_steps if args.lon_steps is not None else base_lon,
            args.radius_m if args.radius_m is not None else base_radius,
        )

    if args.dense:
        lat = (
            args.lat_steps
            if args.lat_steps is not None
            else DEFAULT_DENSE_MANHATTAN_LAT_STEPS
        )
        lon = (
            args.lon_steps
            if args.lon_steps is not None
            else DEFAULT_DENSE_MANHATTAN_LON_STEPS
        )
        radius = (
            args.radius_m if args.radius_m is not None else DEFAULT_DENSE_MANHATTAN_RADIUS_M
        )
        return (lat, lon, radius)

    return (
        args.lat_steps if args.lat_steps is not None else DEFAULT_MANHATTAN_LAT_STEPS,
        args.lon_steps if args.lon_steps is not None else DEFAULT_MANHATTAN_LON_STEPS,
        args.radius_m if args.radius_m is not None else DEFAULT_MANHATTAN_RADIUS_M,
    )


def resolve_preset(
    args: argparse.Namespace,
) -> tuple[AreaPreset | None, dict[str, float], int, int, float, str]:
    chosen: list[str] = []
    if args.area:
        chosen.append(args.area)
    for name in PRESET_FLAG_NAMES:
        if getattr(args, name, False):
            chosen.append(name)

    if len(chosen) > 1:
        raise ValueError(f"Choose only one area preset, got: {', '.join(chosen)}")

    if chosen:
        key = chosen[0]
        if key not in AREA_PRESETS:
            raise ValueError(f"Unknown area preset: {key}")
        preset = AREA_PRESETS[key]
        lat_steps, lon_steps, radius_m = resolve_grid_params(args, preset)
        return (preset, preset.bounds, lat_steps, lon_steps, radius_m, preset.label)

    lat_steps, lon_steps, radius_m = resolve_grid_params(args, None)
    return (None, MANHATTAN_BOUNDS, lat_steps, lon_steps, radius_m, "Manhattan")


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch places into SQLite or Snowflake.")
    parser.add_argument("--dry-run", action="store_true", help="Print grid only; no API/DB.")
    parser.add_argument("--snowflake", action="store_true", help="Load into Snowflake RAW.PLACES.")
    parser.add_argument(
        "--lat-steps",
        type=int,
        default=None,
        help="Grid rows (overrides preset; default 1 for pilots, 8 for full Manhattan).",
    )
    parser.add_argument(
        "--lon-steps",
        type=int,
        default=None,
        help="Grid columns (overrides preset; default 1 for pilots, 5 for full Manhattan).",
    )
    parser.add_argument(
        "--radius-m",
        type=float,
        default=None,
        help="Search radius in meters (overrides preset).",
    )
    parser.add_argument("--sleep", type=float, default=0.12, help="Seconds between API calls.")
    parser.add_argument("--max-cells", type=int, default=0, help="Stop after N grid cells.")
    parser.add_argument(
        "--types",
        default=",".join(DEFAULT_INCLUDED_TYPES),
        help="Comma-separated includedTypes (one type per API call).",
    )
    parser.add_argument(
        "--area",
        choices=sorted(AREA_PRESETS.keys()),
        help="Pilot area preset (alternative to neighborhood flags).",
    )
    parser.add_argument("--kips-bay", action="store_true", help="Kips Bay, NYC pilot preset.")
    parser.add_argument("--murray-hill", action="store_true", help="Murray Hill, NYC pilot preset.")
    parser.add_argument("--manhattan-beach", action="store_true", help="Manhattan Beach, CA pilot preset.")
    parser.add_argument(
        "--dense",
        action="store_true",
        help="Use 3x3 / 550m grid for pilots (or 12x10 / 700m for full Manhattan) unless overridden.",
    )
    args = parser.parse_args()

    included = tuple(t.strip() for t in args.types.split(",") if t.strip())
    if not included:
        print("No types after parsing --types", file=sys.stderr)
        return 2

    try:
        preset, bounds, lat_steps, lon_steps, radius_m, area_label = resolve_preset(args)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2

    borough = preset.borough if preset else "Manhattan"
    ingest_source = f"google_places_nearby:{preset.slug if preset else 'manhattan'}"

    grid = list(
        iter_grid(
            south=bounds["south"],
            north=bounds["north"],
            west=bounds["west"],
            east=bounds["east"],
            lat_steps=lat_steps,
            lon_steps=lon_steps,
        )
    )
    total_cells = len(grid)
    if args.max_cells > 0:
        grid = grid[: args.max_cells]

    target = "Snowflake" if args.snowflake else "SQLite"
    mode = "dense" if args.dense else "standard"
    est_calls = len(grid) * len(included)
    print(
        f"Target: {target} | Area: {area_label} | Mode: {mode} | Borough/area tag: {borough} | "
        f"Grid: {lat_steps}x{lon_steps} = {total_cells} cells (running {len(grid)}), "
        f"radius={radius_m}m, types={included}, est_api_calls={est_calls}"
    )

    if args.dry_run:
        print("Dry run; exiting.")
        return 0

    api_key = google_places_api_key()
    now_fn = snowflake_utc_now_iso if args.snowflake else utc_now_iso
    api_calls = 0
    upserts = 0
    err: str | None = None

    if args.snowflake:
        with snowflake_connection() as conn:
            run_started = now_fn()
            run_key = start_fetch_run(
                conn,
                started_at=run_started,
                source=ingest_source,
                grid_rows=lat_steps,
                grid_cols=lon_steps,
                search_radius_m=radius_m,
                types_requested=",".join(included),
            )
            conn.commit()
            try:
                for i, (lat, lon) in enumerate(grid):
                    for place_type in included:
                        if args.sleep > 0 and api_calls > 0:
                            time.sleep(args.sleep)
                        data = nearby_search(
                            api_key=api_key,
                            latitude=lat,
                            longitude=lon,
                            radius_m=radius_m,
                            included_types=[place_type],
                        )
                        api_calls += 1
                        places = data.get("places") or []
                        now_iso = now_fn()
                        for p in places:
                            row = parse_place_row(p, borough=borough, source=ingest_source)
                            snowflake_upsert_place(conn, now_iso=now_iso, **row)
                            upserts += 1
                        conn.commit()
                        print(
                            f"  [{api_calls}] cell {i + 1}/{len(grid)} ({lat:.5f},{lon:.5f}) "
                            f"type={place_type} returned {len(places)}"
                        )
            except Exception as e:  # noqa: BLE001
                err = str(e)
                print(err, file=sys.stderr)
            finally:
                finish_fetch_run(
                    conn,
                    run_key=run_key,
                    finished_at=now_fn(),
                    api_calls=api_calls,
                    places_upserted=upserts,
                    error_message=err,
                )
                conn.commit()
        print(
            f"Done. API calls={api_calls}, upsert ops={upserts}, "
            f"target={snowflake_target_label()}"
        )
    else:
        db = sqlite_path()
        conn = connect(db)
        init_schema(conn, project_root() / "schema.sql")

        run_started = now_fn()
        cur = conn.execute(
            """
            INSERT INTO fetch_runs (
              started_at, source, grid_rows, grid_cols, search_radius_m, types_requested,
              api_calls, places_upserted, error_message
            ) VALUES (?, ?, ?, ?, ?, ?, 0, 0, NULL)
            """,
            (run_started, ingest_source, lat_steps, lon_steps, radius_m, ",".join(included)),
        )
        run_id = cur.lastrowid
        conn.commit()

        try:
            for i, (lat, lon) in enumerate(grid):
                for place_type in included:
                    if args.sleep > 0 and api_calls > 0:
                        time.sleep(args.sleep)
                    data = nearby_search(
                        api_key=api_key,
                        latitude=lat,
                        longitude=lon,
                        radius_m=radius_m,
                        included_types=[place_type],
                    )
                    api_calls += 1
                    places = data.get("places") or []
                    now_iso = now_fn()
                    for p in places:
                        row = parse_place_row(p, borough=borough, source=ingest_source)
                        sqlite_upsert_place(conn, now_iso=now_iso, **row)
                        upserts += 1
                    conn.commit()
                    print(
                        f"  [{api_calls}] cell {i + 1}/{len(grid)} ({lat:.5f},{lon:.5f}) "
                        f"type={place_type} returned {len(places)}"
                    )
        except Exception as e:  # noqa: BLE001
            err = str(e)
            print(err, file=sys.stderr)
        finally:
            conn.execute(
                """
                UPDATE fetch_runs SET
                    finished_at = ?, api_calls = ?, places_upserted = ?, error_message = ?
                WHERE id = ?
                """,
                (now_fn(), api_calls, upserts, err, run_id),
            )
            conn.commit()
            conn.close()
        print(f"Done. API calls={api_calls}, upsert ops={upserts}, db={db}")

    return 1 if err else 0


if __name__ == "__main__":
    raise SystemExit(main())
