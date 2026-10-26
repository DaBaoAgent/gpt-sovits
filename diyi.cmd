@echo off
REM diyi.cmd - run diyi.py with the engine venv
setlocal
set "PYTHONPATH="
set "PYTHONHOME="
set "HERE=%~dp0"
set "PY=%HERE%.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo [fail] Engine venv not found: %HERE%.venv
  echo        Run scripts\setup.ps1 from the project root first.
  exit /b 1
)
"%PY%" -X utf8 "%HERE%diyi.py" %*
