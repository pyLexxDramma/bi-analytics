@echo off
echo Starting Project Visualization Dashboard...
echo.
cd /d "%~dp0"
call venv\Scripts\activate.bat
python -m streamlit run project_visualization_app.py
pause

