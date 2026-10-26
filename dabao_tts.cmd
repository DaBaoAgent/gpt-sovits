@echo off
REM dabao_tts.cmd - run dabao_tts.py with the engine venv
REM Usage: dabao_tts.cmd --text-file path\to\full.txt --out path\to\voice.wav --force
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
"%PY%" -X utf8 "%HERE%dabao_tts.py" %*
