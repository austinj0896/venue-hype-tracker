@echo off
setlocal
cd /d "%~dp0.."
python fetch_manhattan_places.py --kips-bay --snowflake
echo.
echo Next: cd dbt ^&^& dbt run
