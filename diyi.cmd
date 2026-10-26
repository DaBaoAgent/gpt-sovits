@echo off
REM diyi.cmd - 快捷入口：用引擎目录里的 .venv 跑 diyi.py
setlocal
set "HERE=%~dp0"
set "PY=%HERE%.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" -X utf8 "%HERE%diyi.py" %*
