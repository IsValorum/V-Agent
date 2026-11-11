@echo off
rem Developer build of the desktop shell. Needs Rust (cargo) on PATH and Visual Studio Build Tools.
rem Optional: set V_AGENT_RUST_BIN to a Rust toolchain bin folder that is not on PATH.
set "CARGO_HOME=%~dp0..\.cargo"
if defined V_AGENT_RUST_BIN set "PATH=%V_AGENT_RUST_BIN%;%PATH%"
set "CARGO_BUILD_JOBS=6"
"%~dp0..\.venv\Scripts\python.exe" "%~dp0build-ui.py"
if errorlevel 1 exit /b 1
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
if errorlevel 1 exit /b 1
cd /d "%~dp0..\desktop\src-tauri"
cargo build --release
exit /b %errorlevel%
