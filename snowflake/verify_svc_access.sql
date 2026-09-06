-- Run in snowsql AS the service user (not Snowsight admin + USE ROLE):
--   snowsql -a YOUR_ACCOUNT -u VENUE_SWIPER_SVC -r VENUE_SWIPER_APP -w VENUE_HYPE_WH -f snowflake/verify_svc_access.sql
--
-- Copy CURRENT_ACCOUNT() + CURRENT_REGION() into Streamlit secrets comparison.

SELECT
    CURRENT_USER() AS snowflake_user,
    CURRENT_ROLE() AS snowflake_role,
    CURRENT_ACCOUNT() AS account_locator,
    CURRENT_ORGANIZATION_NAME() AS org_name,
    CURRENT_ACCOUNT_NAME() AS account_name,
    CURRENT_REGION() AS region;

SELECT COUNT(*) AS manhattan_beach_venues
FROM VENUE_HYPE.STAGING_MARTS.DIM_PLACES
WHERE borough = 'Manhattan Beach';

SHOW GRANTS TO ROLE VENUE_SWIPER_APP;
