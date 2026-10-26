@echo off
REM dabao_tts.cmd - 快捷入口：用引擎目录里的 .venv 跑 dabao_tts.py
REM 用法: dabao_tts.cmd --text-file <全篇.txt> --out <配音.wav> --force
setlocal
set "HERE=%~dp0"
set "PY=%HERE%.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" -X utf8 "%HERE%dabao_tts.py" %*
