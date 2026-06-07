@echo off
setlocal
set ROOT=%~dp0..
if not defined SNOWSQL_CONNECTION set SNOWSQL_CONNECTION=venue_hype
echo Bootstrapping VENUE_HYPE via snowsql connection: %SNOWSQL_CONNECTION%
snowsql -c %SNOWSQL_CONNECTION% -f "%ROOT%\snowflake\setup.sql"
