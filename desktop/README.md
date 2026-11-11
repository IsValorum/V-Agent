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
| `web/` | **Generated** copy of the interface (`scripts/sync-ui.py`), not in git. |

Build with `scripts\build-desktop.cmd` (developer build) or `scripts\build-release.cmd` (installer).
