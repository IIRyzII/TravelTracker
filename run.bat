@echo off
cd /d "%~dp0"
echo Starting ORBIT at http://127.0.0.1:5000 ...
start "" http://127.0.0.1:5000
python app.py
