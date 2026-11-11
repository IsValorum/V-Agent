# scripts/ — build and release

| Script | What it does |
|---|---|
| `build-ui.py` | Assembles the interface from `agent/ui/` into `agent/ui/dist/` and checks that every text has its five translations. Run it after editing anything in `agent/ui/`. |
| `build-desktop.cmd` | Developer build of the desktop app. |
| `build-core.cmd` | Packages the core (`dist/core/strata-core.exe`) with PyInstaller for the developer build. |
| `build-release.cmd` | Official installer: clean data, no engines, notices, PyInstaller, then the NSIS installer in `dist-release/`. |
| `core.spec` | PyInstaller recipe for the core (`V_AGENT_RELEASE=1` for the official build). |
| `prepare_release.py` | Stages the empty, personal-data-free starting files for the installer. |
| `third_party_notices.py` | Writes `THIRD-PARTY-NOTICES.md` from the bundled packages. |
| `prepare-native-icons.py` | Builds app icons and logos from the original artwork. |
| `release.py` | Maintainer only: signing key, signed installer manifests and signed minor updates. See [RELEASING.md](../RELEASING.md). |

Set `V_AGENT_RUST_BIN` to a Rust toolchain `bin` folder if `cargo` is not on your `PATH`.
