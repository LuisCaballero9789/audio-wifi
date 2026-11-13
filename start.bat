@echo off
rem Starts Audio WiFi. Installs the dependencies on first run.
cd /d "%~dp0"
py -c "import soundcard, numpy" 2>nul
if errorlevel 1 (
    echo Installing dependencies, first run only...
    py -m pip install -r requirements.txt
)
py audio_wifi.py %*
pause
