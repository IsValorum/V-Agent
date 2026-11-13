@echo off
rem Official V-Agent installer: fails if Git is dirty, builds inside a clean temporary worktree
rem (no engines, no seeds, no personal data), and verifies the packaged output.
rem Result: dist-release\V-Agent_<version>_x64-setup.exe (sign it with scripts\release.py --sign).
setlocal
cd /d "%~dp0.."
".venv\Scripts\python.exe" "scripts\clean_release_build.py" %*
set "EXIT_CODE=%ERRORLEVEL%"
endlocal & exit /b %EXIT_CODE%
