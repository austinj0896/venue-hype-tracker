-- Venue Swiper Streamlit app — Snowflake bootstrap
-- Run after setup.sql and dbt (dim_places must exist):
--   snowsql -c venue_hype -f snowflake/setup_app.sql
--
-- Then deploy Python files:
--   scripts\deploy_venue_swiper.bat

-- Warehouse comes from your snowsql connection (warehousename in config).

USE DATABASE VENUE_HYPE;
CREATE SCHEMA IF NOT EXISTS VENUE_HYPE.APP;

USE SCHEMA VENUE_HYPE.APP;

-- In-app user identity (email entered at login). Snowflake auth still gates app access.
CREATE TABLE IF NOT EXISTS VENUE_RATINGS (
    RATING_ID         NUMBER AUTOINCREMENT START 1 INCREMENT 1,
    USER_EMAIL        VARCHAR NOT NULL,
    GOOGLE_PLACE_ID   VARCHAR NOT NULL,
    PLACE_NAME        VARCHAR,
    BOROUGH           VARCHAR NOT NULL DEFAULT 'Manhattan Beach',
    RATING            FLOAT,
    STATUS            VARCHAR NOT NULL,  -- 'rated' | 'skipped'
    CREATED_AT        TIMESTAMP_NTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    UPDATED_AT        TIMESTAMP_NTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    CONSTRAINT UQ_VENUE_RATINGS_USER_PLACE UNIQUE (USER_EMAIL, GOOGLE_PLACE_ID),
    CONSTRAINT CHK_VENUE_RATINGS_STATUS CHECK (STATUS IN ('rated', 'skipped')),
    CONSTRAINT CHK_VENUE_RATINGS_VALUE CHECK (
        (STATUS = 'skipped' AND RATING IS NULL)
        OR (STATUS = 'rated' AND RATING IS NOT NULL AND RATING >= 0 AND RATING <= 5)
    )
);

-- Snowflake standard tables do not use indexes (hybrid tables only).
    DIRECTORY = (ENABLE = TRUE)
    COMMENT = 'Stage for Venue Swiper Streamlit app source files';

-- Run deploy_venue_swiper.bat to PUT streamlit_app.py, then uncomment or run:
--
-- CREATE OR REPLACE STREAMLIT VENUE_SWIPER
--     FROM '@VENUE_HYPE.APP.VENUE_SWIPER_STAGE'
--     MAIN_FILE = 'streamlit_app.py'
--     QUERY_WAREHOUSE = VENUE_HYPE_WH
--     TITLE = 'Manhattan Beach Venue Swiper'
--     COMMENT = 'Swipe-style venue ratings for Manhattan Beach pilots';

-- Share with viewers (adjust role name):
-- GRANT USAGE ON DATABASE VENUE_HYPE TO ROLE <viewer_role>;
-- GRANT USAGE ON SCHEMA VENUE_HYPE.APP TO ROLE <viewer_role>;
-- GRANT USAGE ON STREAMLIT VENUE_HYPE.APP.VENUE_SWIPER TO ROLE <viewer_role>;
-- GRANT SELECT ON TABLE VENUE_HYPE.STAGING_MARTS.DIM_PLACES TO ROLE <viewer_role>;
-- GRANT SELECT, INSERT, UPDATE ON TABLE VENUE_HYPE.APP.VENUE_RATINGS TO ROLE <viewer_role>;

SELECT 'VENUE_HYPE APP bootstrap complete' AS STATUS;
