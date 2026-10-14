@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 goto use_python
py -3.12 --version >nul 2>nul
if errorlevel 1 goto use_python
py -3.12 run.py --check
goto finished
:use_python
python run.py --check
:finished
if errorlevel 1 (
  echo.
  echo Aether could not start. Read the error above.
  pause
)
endlocal
