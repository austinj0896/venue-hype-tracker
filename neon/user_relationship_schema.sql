-- Après relationship status, partner linking, and in-app notifications.
-- Apply via partner_store.ensure_relationship_schema() or Neon SQL Editor.

-- Profile columns (also added by ensure_schema ALTERs)
ALTER TABLE user_profiles
    ADD COLUMN IF NOT EXISTS relationship_status TEXT;
ALTER TABLE user_profiles
    ADD COLUMN IF NOT EXISTS open_to_dates BOOLEAN;
ALTER TABLE user_profiles
    ADD COLUMN IF NOT EXISTS profile_visibility TEXT NOT NULL DEFAULT 'private';

CREATE INDEX IF NOT EXISTS idx_user_profiles_visibility
    ON user_profiles (profile_visibility)
    WHERE profile_complete = TRUE;

CREATE TABLE IF NOT EXISTS partner_link_requests (
    request_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    from_email    TEXT NOT NULL,
    to_email      TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'pending',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    responded_at  TIMESTAMPTZ,
    CONSTRAINT partner_link_requests_status_chk
        CHECK (status IN ('pending', 'accepted', 'declined', 'cancelled', 'expired')),
    CONSTRAINT partner_link_requests_not_self_chk
        CHECK (lower(from_email) <> lower(to_email))
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_partner_link_requests_pending
    ON partner_link_requests (lower(from_email), lower(to_email))
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_partner_link_requests_to
    ON partner_link_requests (lower(to_email), status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_partner_link_requests_from
    ON partner_link_requests (lower(from_email), status, created_at DESC);

CREATE TABLE IF NOT EXISTS partner_links (
    user_email_a       TEXT NOT NULL,
    user_email_b       TEXT NOT NULL,
    linked_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    requested_by_email TEXT NOT NULL,
    PRIMARY KEY (user_email_a, user_email_b),
    CONSTRAINT partner_links_ordered_chk CHECK (user_email_a < user_email_b)
);

CREATE INDEX IF NOT EXISTS idx_partner_links_a ON partner_links (user_email_a);
CREATE INDEX IF NOT EXISTS idx_partner_links_b ON partner_links (user_email_b);

CREATE TABLE IF NOT EXISTS user_notifications (
    notification_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_email      TEXT NOT NULL,
    kind            TEXT NOT NULL,
    payload         JSONB NOT NULL DEFAULT '{}'::jsonb,
    read_at         TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT user_notifications_kind_chk
        CHECK (kind IN ('partner_request', 'partner_accepted', 'partner_declined'))
);

CREATE INDEX IF NOT EXISTS idx_user_notifications_inbox
    ON user_notifications (lower(user_email), created_at DESC);

CREATE INDEX IF NOT EXISTS idx_user_notifications_unread
    ON user_notifications (lower(user_email), created_at DESC)
    WHERE read_at IS NULL;
