@echo off
REM Run Research Tracker on this computer: http://127.0.0.1:8000
REM Needs Python 3.11+ (https://www.python.org/downloads/ - tick "Add python.exe to PATH")
cd /d "%~dp0"
where python >nul 2>nul || (echo [!] Please install Python 3.11+ from https://www.python.org/downloads/ & pause & exit /b 1)
if not exist .venv python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip >nul
pip install -r requirements.txt || (echo [!] Installing packages failed & pause & exit /b 1)
set DEBUG=1
python manage.py migrate
python manage.py seed_demo
echo.
echo  Login:  demo@example.com  /  demo-pass-2026
echo  (Create your own admin later with: python manage.py createsuperuser)
echo.
start "" http://127.0.0.1:8000
python manage.py runserver
pause
