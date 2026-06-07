@echo off
setlocal
cd /d "%~dp0..\streamlit\venue_swiper"
if not exist .streamlit\secrets.toml (
  echo.
  echo Create .streamlit\secrets.toml from .streamlit\secrets.toml.example first.
  echo.
  exit /b 1
)
pip install -r requirements.txt
streamlit run streamlit_app.py
