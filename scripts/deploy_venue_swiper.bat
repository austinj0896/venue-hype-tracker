@echo off
setlocal
set ROOT=%~dp0..
if not defined SNOWSQL_CONNECTION set SNOWSQL_CONNECTION=venue_hype

echo Bootstrapping APP schema and ratings tables...
snowsql -c %SNOWSQL_CONNECTION% -f "%ROOT%\snowflake\setup_app.sql"
echo Bootstrap finished (warehouse/index warnings are OK if objects already exist).

cd /d "%ROOT%\streamlit\venue_swiper"
echo Uploading Streamlit app to stage from %CD%...
snowsql -c %SNOWSQL_CONNECTION% -q "PUT file://streamlit_app.py @VENUE_HYPE.APP.VENUE_SWIPER_STAGE AUTO_COMPRESS=FALSE OVERWRITE=TRUE;"
if errorlevel 1 (
  echo PUT streamlit_app.py failed.
  exit /b 1
)
snowsql -c %SNOWSQL_CONNECTION% -q "PUT file://environment.sis.yml @VENUE_HYPE.APP.VENUE_SWIPER_STAGE AUTO_COMPRESS=FALSE OVERWRITE=TRUE;"
snowsql -c %SNOWSQL_CONNECTION% -q "PUT file://.streamlit/config.toml @VENUE_HYPE.APP.VENUE_SWIPER_STAGE/.streamlit/ AUTO_COMPRESS=FALSE OVERWRITE=TRUE;"

echo Creating or replacing Streamlit app object...
snowsql -c %SNOWSQL_CONNECTION% -q "CREATE OR REPLACE STREAMLIT VENUE_HYPE.APP.VENUE_SWIPER FROM '@VENUE_HYPE.APP.VENUE_SWIPER_STAGE' MAIN_FILE = 'streamlit_app.py' QUERY_WAREHOUSE = VENUE_HYPE_WH TITLE = 'Vesper - Manhattan Beach' COMMENT = 'Vesper-styled venue ratings for Manhattan Beach';"
if errorlevel 1 exit /b 1

echo.
echo Deploy complete. Open in Snowsight:
echo   Data ^> Streamlit ^> VENUE_SWIPER (schema APP, database VENUE_HYPE)
echo.
echo To share with viewers, grant access (adjust role as needed):
echo   GRANT USAGE ON DATABASE VENUE_HYPE TO ROLE ^<viewer_role^>;
echo   GRANT USAGE ON SCHEMA VENUE_HYPE.APP TO ROLE ^<viewer_role^>;
echo   GRANT USAGE ON STREAMLIT VENUE_HYPE.APP.VENUE_SWIPER TO ROLE ^<viewer_role^>;
echo   GRANT SELECT ON TABLE VENUE_HYPE.STAGING_MARTS.DIM_PLACES TO ROLE ^<viewer_role^>;
echo   GRANT SELECT, INSERT, UPDATE ON TABLE VENUE_HYPE.APP.VENUE_RATINGS TO ROLE ^<viewer_role^>;
