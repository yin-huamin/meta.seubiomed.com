@echo off
setlocal
cd /d "%~dp0"
python metaweb.py publish >> logs\publish.log 2>&1
endlocal
