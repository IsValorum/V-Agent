# Releasing V-Agent (maintainer only)

Only the holder of the signing key can publish updates that installed copies of V-Agent accept.

## One-time setup

1. Create the GitHub repository and set it in `agent/app_updates.py`:
   `REPOSITORY = 'your-user/V-Agent'`.
2. The signing key was created with `python scripts/release.py --init-key`. It lives in
   `%USERPROFILE%\.v-agent\update-signing-key.pem` and its public half is embedded in
   `agent/app_updates.py`. **Back the .pem file up somewhere safe and private** (for example an
   encrypted USB drive). If it is lost, installed copies cannot receive updates; if it leaks, someone
   else could sign updates. Never commit it.

## Each release

1. Update `VERSION` in `agent/app_updates.py`, `version` in `desktop/src-tauri/tauri.conf.json` and
   `desktop/src-tauri/Cargo.toml`, and `CHANGELOG.md` (same number, e.g. `1.0.1`). Save these files
   as UTF-8 **without** BOM (Tauri and Cargo reject a BOM).
2. Build the official installer (no engines, no personal data):

   ```bat
   scripts\build-release.cmd
   ```

   The result is `dist-release\V-Agent_<version>_x64-setup.exe`.
3. Sign it:

   ```bat
   .venv\Scripts\python scripts\release.py --sign dist-release\V-Agent_<version>_x64-setup.exe --notes "Short summary"
   ```

   This writes `v-agent-update.json` and `v-agent-update.json.sig` next to the installer.
4. Create a GitHub release tagged `v<version>` and upload **all three files**. Installed copies find it
   under *Settings → General → V-Agent updates*.

Optional but recommended: sign the installer with an Authenticode code-signing certificate so Windows
SmartScreen recognises the publisher.

## Minor updates (components channel)

For small fixes to MCP servers, web search, tool descriptions or code checks, no installer is needed.
The channel also carries interface fixes: `ui-patch.css` (style overrides) and
`ui-patch.js` (behaviour), which the window loads on top of the bundled interface when it opens.
Bigger interface changes still need a new installer. Fold each patch into the regular files before
the next installer so that version starts clean.

1. Put only the changed files in a folder (allowed names are listed in `agent/components.py`,
   e.g. `pc_mcp.py`, `buscador_mcp.py`, `mcp_prompt.py`, `scene_probe.js`).
2. Sign them for the current app version with a revision number higher than the last one:

   ```bat
   .venv\Scripts\python scripts\release.py --components path\to\folder --revision 2 --notes "Better web search"
   ```

3. Create a GitHub release tagged `components-<app version>-r<revision>` (for example
   `components-1.0.0-r2`) and upload the changed files plus `v-agent-components.json` and
   `v-agent-components.json.sig`. Users see it in *Settings → General* and it applies on restart.

Components are tied to one app version: after publishing a new installer, start again at `r1`.
In the app, revision N of version X is shown as **"X CN"** (for example `components-1.0.0-r1` is
"1.0.0 C1"); the version number itself does not change.
