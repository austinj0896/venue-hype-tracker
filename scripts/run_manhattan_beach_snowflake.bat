@echo off
setlocal
cd /d "%~dp0.."
python fetch_manhattan_places.py --manhattan-beach --snowflake
echo.
echo Update pilot_bbox_* in dbt/dbt_project.yml if needed, then:
echo   cd dbt ^&^& dbt run ^&^& dbt snapshot ^&^& dbt test
