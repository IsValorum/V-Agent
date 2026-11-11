@echo off
cd /d "%~dp0.."
.venv\Scripts\python.exe scripts\build-ui.py
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -m PyInstaller scripts\core.spec --noconfirm --distpath dist --workpath build\core
if errorlevel 1 exit /b 1
copy /y "desktop\src-tauri\target\release\val-agent.exe" "dist\V-Agent.exe"
echo {"data_dir":"../data"}> dist\val-portable.json
