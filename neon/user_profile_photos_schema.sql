-- Après durable photo assets + profile links.
-- Profile "delete" only removes a row from user_profile_photo_links.
-- Permanent destruction is admin-only (scripts/admin_photos.py).

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS media_photos (
    photo_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    photo_b64          TEXT NOT NULL,
    photo_mime         TEXT NOT NULL DEFAULT 'image/jpeg',
    uploaded_by_email  TEXT,
    byte_length        INTEGER,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_media_photos_uploader
    ON media_photos (uploaded_by_email);

CREATE INDEX IF NOT EXISTS idx_media_photos_created
    ON media_photos (created_at DESC);

CREATE TABLE IF NOT EXISTS user_profile_photo_links (
    user_email  TEXT NOT NULL,
    photo_id    UUID NOT NULL REFERENCES media_photos (photo_id) ON DELETE CASCADE,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    linked_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_email, photo_id),
    CONSTRAINT uq_user_profile_photo_links_order UNIQUE (user_email, sort_order),
    CONSTRAINT chk_user_profile_photo_links_order CHECK (sort_order >= 0 AND sort_order < 12)
);

CREATE INDEX IF NOT EXISTS idx_user_profile_photo_links_user
    ON user_profile_photo_links (user_email, sort_order);

CREATE INDEX IF NOT EXISTS idx_user_profile_photo_links_photo
    ON user_profile_photo_links (photo_id);

-- Optional: migrate rows from the older combined gallery table if present.
DO $$
BEGIN
    IF to_regclass('public.user_profile_photos') IS NOT NULL
       AND to_regclass('public.media_photos') IS NOT NULL THEN
        INSERT INTO media_photos (photo_id, photo_b64, photo_mime, uploaded_by_email, created_at, updated_at)
        SELECT
            gen_random_uuid(),
            upp.photo_b64,
            coalesce(nullif(upp.photo_mime, ''), 'image/jpeg'),
            upp.user_email,
            upp.created_at,
            upp.updated_at
        FROM user_profile_photos upp
        WHERE upp.photo_b64 IS NOT NULL
          AND length(upp.photo_b64) > 0
          AND NOT EXISTS (
              SELECT 1
              FROM media_photos mp
              WHERE mp.uploaded_by_email = upp.user_email
                AND mp.photo_b64 = upp.photo_b64
          );

        INSERT INTO user_profile_photo_links (user_email, photo_id, sort_order, linked_at)
        SELECT DISTINCT ON (upp.user_email, upp.sort_order)
            upp.user_email,
            mp.photo_id,
            upp.sort_order,
            coalesce(upp.created_at, NOW())
        FROM user_profile_photos upp
        JOIN media_photos mp
          ON mp.uploaded_by_email = upp.user_email
         AND mp.photo_b64 = upp.photo_b64
        ORDER BY upp.user_email, upp.sort_order, mp.created_at DESC
        ON CONFLICT DO NOTHING;
    END IF;
END $$;
