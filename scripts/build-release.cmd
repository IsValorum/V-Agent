@echo off
rem Official V-Agent installer: no engines, no seeds, no personal data.
rem Result: dist-release\V-Agent_<version>_x64-setup.exe (sign it with scripts\release.py --sign).
setlocal
cd /d "%~dp0.."
set "CARGO_HOME=%~dp0..\.cargo"
rem Optional: set V_AGENT_RUST_BIN to a Rust toolchain bin folder that is not on PATH.
if defined V_AGENT_RUST_BIN set "PATH=%V_AGENT_RUST_BIN%;%PATH%"
set "CARGO_BUILD_JOBS=6"
.venv\Scripts\python.exe scripts\build-ui.py || exit /b 1
.venv\Scripts\python.exe scripts\prepare_release.py || exit /b 1
.venv\Scripts\python.exe scripts\third_party_notices.py || exit /b 1
set "V_AGENT_RELEASE=1"
.venv\Scripts\python.exe -m PyInstaller scripts\core.spec --noconfirm --distpath dist-release --workpath build\core-release || exit /b 1
set "V_AGENT_RELEASE="
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" || exit /b 1
cd /d "%~dp0..\desktop"
call npx --yes @tauri-apps/cli@2 build --bundles nsis || exit /b 1
cd /d "%~dp0.."
for %%F in ("desktop\src-tauri\target\release\bundle\nsis\V-Agent_*_x64-setup.exe") do copy /y "%%F" "dist-release\" >nul
echo Installer ready in dist-release
endlocal
