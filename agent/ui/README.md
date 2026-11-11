# agent/ui/ — the interface

Everything people see in V-Agent. Tauri 2 draws its windows with the system's web engine (WebView2
on Windows), so the interface is HTML, CSS and JavaScript; this folder is its source.

```
v-agent.html        page skeleton: markup, and the ordered list of parts (/*@include …*/)
styles/
  base.css          layout, typography and the original components
  panels.css        windows, palettes and styles (glass, soft, Art Deco), newer components
app/                the program — one shared scope, assembled in the order listed in v-agent.html
standalone/         scripts loaded on their own: i18n.js (translations), motion.js, mcp.js
locales.json        every visible text in es, en, pt, fr and de
dist/               BUILT by scripts/build-ui.py — not in git, never edit
```

## The program (`app/`)

| File | What it does |
|---|---|
| `core-connection.js` | Finds the local core, loads minor-update patches, watches automatic updates. |
| `startup.js` | Starts the program: settings, theme, defaults. |
| `markdown.js` | Renders replies: Markdown, code blocks, previews, "save and check". |
| `conversations.js` | Chat list, projects in the sidebar, archive, export. |
| `chat.js` | The conversation view: messages, tool calls, approvals, drafts. |
| `composer.js` | Message box, attachments, sending and streaming. |
| `model-controls.js` | Model selection, loading, context, templates, MTP, performance stats. |
| `settings.js` | Settings window and the side panel. |
| `engine-controls.js` | Engines (llama.cpp, Strata, APIs): variants, versions, updates. |
| `model-panel.js` | The *Model and engine* window and per-model preferences. |
| `sessions.js` | Saving chats to disk, import/export of sessions. |
| `shell.js` | Settings layout, dialogs, custom title bar, segmented controls, menus. |
| `windows.js` | Floating windows: tiling, sizes, motion. |
| `tools.js` | Tools window and agent modes. |
| `palette.js` | Palettes, styles and the app icon. |
| `load-settings.js` | Per-model load settings. |
| `plugins.js` | Extensions: market and plugins. |
| `tour.js` | First-run tour; V-Agent updates and minor updates in Settings → General. |
| `models.js` | *Models* window: Hugging Face, downloads, LM Studio / Unsloth import and export. |
| `controls.js` | Composer buttons and the model/tools/context popovers. |
| `events.js` | Remaining event wiring and the end of start-up. |

All parts run inside one `initializeAgent()` function, so a function or variable defined in one part
is visible to the parts after it. That is why they are assembled into the page rather than loaded as
separate `<script>` files.

## Working on it

1. Edit the files here.
2. Run `python scripts/build-ui.py` (it also checks that every text has all five translations).
3. Reload `http://127.0.0.1:19381` if you run the core from source, or rebuild the desktop app.

Use palette tokens (`--accent`, `--panel`, `--text`, `--muted`, `--border`…) for colours, and
`uiText('…')` with an entry in `locales.json` for any visible text.
