#!/usr/bin/env python3
"""Admin tool: list / permanently destroy Après media photos (Neon).

This is intentionally NOT part of the Streamlit user app. Profile "delete"
only unlinks a photo from a user. Use this CLI to destroy bytes forever.

Setup
-----
Uses DATABASE_URL from the repo `.env` (or the environment).

  cd ~/CursorProjects/venue_hype_tracker
  python3 scripts/admin_photos.py --help

Common commands
---------------
  # List orphans (uploaded but not on any profile)
  python3 scripts/admin_photos.py orphans

  # List everything (metadata only — no image bytes)
  python3 scripts/admin_photos.py list --limit 50

  # Destroy one photo by UUID (also removes any remaining profile links)
  python3 scripts/admin_photos.py destroy --id <uuid> --yes

  # Destroy all orphans older than N days
  python3 scripts/admin_photos.py destroy-orphans --older-than-days 30 --yes

  # Destroy every photo for an email (linked + any they uploaded that are orphaned)
  python3 scripts/admin_photos.py destroy-uploader --email user@example.com --yes
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_env() -> None:
    env_path = ROOT / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _connect():
    import psycopg2
    from psycopg2.extras import RealDictCursor

    url = os.environ.get("DATABASE_URL") or os.environ.get("NEON_DATABASE_URL")
    if not url:
        raise SystemExit("Missing DATABASE_URL (set in .env or the environment).")
    return psycopg2.connect(url, connect_timeout=20, cursor_factory=RealDictCursor)


def _ensure_tables(cur) -> None:
    cur.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS media_photos (
            photo_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            photo_b64          TEXT NOT NULL,
            photo_mime         TEXT NOT NULL DEFAULT 'image/jpeg',
            uploaded_by_email  TEXT,
            byte_length        INTEGER,
            created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_profile_photo_links (
            user_email  TEXT NOT NULL,
            photo_id    UUID NOT NULL REFERENCES media_photos (photo_id) ON DELETE CASCADE,
            sort_order  INTEGER NOT NULL DEFAULT 0,
            linked_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (user_email, photo_id)
        )
        """
    )


def cmd_list(cur, *, limit: int, orphans_only: bool) -> None:
    if orphans_only:
        cur.execute(
            """
            select
                m.photo_id,
                m.uploaded_by_email,
                m.photo_mime,
                coalesce(m.byte_length, length(m.photo_b64)) as byte_length,
                m.created_at,
                0 as link_count
            from media_photos m
            left join user_profile_photo_links l on l.photo_id = m.photo_id
            where l.photo_id is null
            order by m.created_at desc
            limit %s
            """,
            [limit],
        )
    else:
        cur.execute(
            """
            select
                m.photo_id,
                m.uploaded_by_email,
                m.photo_mime,
                coalesce(m.byte_length, length(m.photo_b64)) as byte_length,
                m.created_at,
                (select count(*) from user_profile_photo_links l where l.photo_id = m.photo_id)
                    as link_count
            from media_photos m
            order by m.created_at desc
            limit %s
            """,
            [limit],
        )
    rows = cur.fetchall()
    if not rows:
        print("(none)")
        return
    print(f"{'photo_id':36}  {'links':5}  {'bytes':>8}  {'uploader':28}  created_at")
    for r in rows:
        print(
            f"{r['photo_id']}  {r['link_count']:<5}  {int(r['byte_length'] or 0):8d}  "
            f"{(r['uploaded_by_email'] or '-'):28}  {r['created_at']}"
        )
    print(f"\n{len(rows)} row(s)")


def cmd_destroy(cur, *, photo_id: str, yes: bool) -> None:
    cur.execute(
        """
        select photo_id, uploaded_by_email, created_at,
               (select count(*) from user_profile_photo_links l where l.photo_id = m.photo_id) as link_count
        from media_photos m
        where photo_id = %s
        """,
        [photo_id],
    )
    row = cur.fetchone()
    if not row:
        raise SystemExit(f"No media_photos row for id={photo_id}")
    print(
        f"Destroy {row['photo_id']} uploader={row['uploaded_by_email']} "
        f"links={row['link_count']} created={row['created_at']}"
    )
    if not yes:
        raise SystemExit("Refusing without --yes")
    cur.execute("delete from media_photos where photo_id = %s", [photo_id])
    print(f"Deleted {cur.rowcount} media row(s) (links cascade).")


def cmd_destroy_orphans(cur, *, older_than_days: int, yes: bool) -> None:
    cur.execute(
        """
        select m.photo_id
        from media_photos m
        left join user_profile_photo_links l on l.photo_id = m.photo_id
        where l.photo_id is null
          and m.created_at < NOW() - (%s || ' days')::interval
        """,
        [str(int(older_than_days))],
    )
    ids = [r["photo_id"] for r in cur.fetchall()]
    print(f"Orphans older than {older_than_days}d: {len(ids)}")
    if not ids:
        return
    if not yes:
        raise SystemExit("Refusing without --yes (dry run listed count only)")
    cur.execute(
        """
        delete from media_photos m
        where m.photo_id in (
            select m2.photo_id
            from media_photos m2
            left join user_profile_photo_links l on l.photo_id = m2.photo_id
            where l.photo_id is null
              and m2.created_at < NOW() - (%s || ' days')::interval
        )
        """,
        [str(int(older_than_days))],
    )
    print(f"Destroyed {cur.rowcount} orphan photo(s).")


def cmd_destroy_uploader(cur, *, email: str, yes: bool) -> None:
    email_n = email.strip().lower()
    cur.execute(
        """
        select count(*) as n from media_photos
        where lower(uploaded_by_email) = lower(%s)
           or photo_id in (
                select photo_id from user_profile_photo_links
                where lower(user_email) = lower(%s)
           )
        """,
        [email_n, email_n],
    )
    n = int(cur.fetchone()["n"])
    print(f"Photos for {email_n}: {n}")
    if not n:
        return
    if not yes:
        raise SystemExit("Refusing without --yes")
    # Unlink first (explicit), then destroy assets uploaded by / linked to them.
    cur.execute(
        "delete from user_profile_photo_links where lower(user_email) = lower(%s)",
        [email_n],
    )
    print(f"Unlinked {cur.rowcount} profile link(s).")
    cur.execute(
        "delete from media_photos where lower(uploaded_by_email) = lower(%s)",
        [email_n],
    )
    print(f"Destroyed {cur.rowcount} media row(s).")


def main(argv: list[str] | None = None) -> int:
    _load_env()
    parser = argparse.ArgumentParser(
        description="Admin: list/destroy Après media_photos (outside the Streamlit app)."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="List photo metadata")
    p_list.add_argument("--limit", type=int, default=50)

    p_orph = sub.add_parser("orphans", help="List unlinked photos")
    p_orph.add_argument("--limit", type=int, default=100)

    p_des = sub.add_parser("destroy", help="Permanently delete one photo by UUID")
    p_des.add_argument("--id", required=True, help="media_photos.photo_id UUID")
    p_des.add_argument("--yes", action="store_true")

    p_do = sub.add_parser("destroy-orphans", help="Permanently delete orphaned photos")
    p_do.add_argument("--older-than-days", type=int, default=30)
    p_do.add_argument("--yes", action="store_true")

    p_du = sub.add_parser("destroy-uploader", help="Destroy photos for an email")
    p_du.add_argument("--email", required=True)
    p_du.add_argument("--yes", action="store_true")

    args = parser.parse_args(argv)
    conn = _connect()
    try:
        with conn:
            with conn.cursor() as cur:
                _ensure_tables(cur)
                if args.cmd == "list":
                    cmd_list(cur, limit=args.limit, orphans_only=False)
                elif args.cmd == "orphans":
                    cmd_list(cur, limit=args.limit, orphans_only=True)
                elif args.cmd == "destroy":
                    cmd_destroy(cur, photo_id=args.id, yes=args.yes)
                elif args.cmd == "destroy-orphans":
                    cmd_destroy_orphans(
                        cur, older_than_days=args.older_than_days, yes=args.yes
                    )
                elif args.cmd == "destroy-uploader":
                    cmd_destroy_uploader(cur, email=args.email, yes=args.yes)
                else:
                    raise SystemExit(f"Unknown command: {args.cmd}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
