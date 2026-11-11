# desktop/ — the Windows app

A small [Tauri 2](https://tauri.app) shell in Rust. It opens the window, starts the core
(`core/strata-core.exe`) and talks to it on `127.0.0.1:19380`.

| Path | What it is |
|---|---|
| `src-tauri/src/main.rs` | Window (custom title bar, taskbar icon per palette), starting and stopping the core, the side browser panel and the user guide. |
| `src-tauri/tauri.conf.json` | App name, version, bundled files and the NSIS installer (languages, install folder, hooks). |
| `src-tauri/windows/hooks.nsh` | Installer hooks: remembers the chosen language; optional data removal on uninstall. |
| `src-tauri/capabilities/`, `permissions/` | What the window is allowed to call. |
| `src-tauri/icons/` | App icons for every palette. |


The window shows the interface built from [`agent/ui/`](../agent/ui/) into `agent/ui/dist/`
(`frontendDist` in `tauri.conf.json`), so the desktop app and the core always use the same files.

Build with `scripts\build-desktop.cmd` (developer build) or `scripts\build-release.cmd` (installer).
