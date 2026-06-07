@echo off
setlocal
cd /d "%~dp0.."
python fetch_manhattan_places.py --murray-hill --snowflake
echo.
echo Next: cd dbt ^&^& dbt run ^&^& dbt snapshot ^&^& dbt test
