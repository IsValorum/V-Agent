# agent/ui/ — the interface

Everything people see in V-Agent. Tauri 2 draws its windows with the system's web engine (WebView2
on Windows), so the interface is HTML, CSS and JavaScript; this folder is its source.

```
v-agent.html        page skeleton: markup, and the ordered list of parts (/*@include …*/)
styles/
  base/             numbered parts placed inside the page: foundation, workspace, chrome, menus, panels
  panels/           numbered parts published joined as /assets/ui-panels.css: windows, styles (soft,
                    glass, Art Deco), models window, engines, states. Each part is a later layer of the
                    same cascade, so the numbers are the order the rules apply in.
app/                the program — one shared scope, assembled in the order listed in v-agent.html
  core/             start-up, the connection to the core, windows, events, the title bar and the tour
  chat/             replies, conversations, the message box and its "+" menu, saved sessions
  models/           model selection and loading, engines and their updates, the Models window
  settings/         the settings window, client preferences, palettes
  agent/            agent modes, thinking/access menus, approvals, tools and plugins
standalone/         scripts loaded on their own: i18n.js (translations), motion.js, mcp.js
locales.json        every visible text in all 14 interface languages (Spanish is the source)
dist/               BUILT by scripts/build-ui.py — not in git, never edit
```

## The program (`app/`)

| File | What it does |
|---|---|
| `core/core-connection.js` | Finds the local core, loads minor-update patches, watches V-Agent updates, update badges. |
| `core/startup.js` | Starts the program: settings, theme, defaults. |
| `chat/markdown.js` | Renders replies: Markdown, code blocks, previews, "save and check". |
| `chat/conversations.js` | Chat list, projects in the sidebar, archive, export. |
| `chat/chat.js` | The conversation view: messages, tool calls, approvals, drafts. |
| `chat/composer.js` | Message box, attachments, sending and streaming. |
| `models/model-controls.js` | Model selection, loading, context, templates, MTP, performance stats. |
| `settings/settings.js` | Settings window and the side panel. |
| `models/engine-controls.js` | Engines (llama.cpp, Strata, Strata Rust, Project Maya, APIs): variants, versions. |
| `models/model-panel.js` | The *Model and engine* window and per-model preferences. |
| `chat/sessions.js` | Saving chats to disk, import/export of sessions. |
| `settings/settings-hub.js` | Settings navigation, categories, the system summary. |
| `chat/composer-menu.js` | The message box's "+" menu. |
| `settings/client-preferences.js` | Language and other preferences restored at start. |
| `agent/agent-controls.js` | Thinking and access menus, in-app confirmations, tool approvals, the agent's questions. |
| `agent/agent-modes.js` | Chat, Light, Standard and Full modes and their selector. |
| `models/engines-and-updates.js` | Hardware, engine recommendations, engine updates and their notices, release notes. |
| `core/window-chrome.js` | Decoration, market page, custom title bar, segmented controls, region labels. |
| `core/windows.js` | Floating windows: tiling, sizes, motion. |
| `agent/tools.js` | Tools window. |
| `settings/palette.js` | Palettes, styles and the app icon. |
| `models/load-settings.js` | Per-model load settings and the engine's own options. |
| `agent/plugins.js` | Extensions: market and plugins. |
| `core/tour.js` | First-run tour; V-Agent updates and minor updates in Settings → General. |
| `models/models.js` | *Models* window: Hugging Face, downloads, LM Studio / Unsloth import and export. |
| `core/controls.js` | Composer buttons and the model/tools/context popovers. |
| `core/events.js` | Remaining event wiring and the end of start-up. |
| `core/polish.js` | Command palette, find in conversation, prompt library, shortcuts, usage. |

All parts run inside one `initializeAgent()` function, so a function or variable defined in one part
is visible to the parts after it. That is why they are assembled into the page rather than loaded as
separate `<script>` files, and why the include order in `v-agent.html` matters more than the folders.

## Working on it

1. Edit the files here.
2. Run `python scripts/build-ui.py` (it also checks that every text has all its translations).
3. Reload `http://127.0.0.1:19381` if you run the core from source, or rebuild the desktop app.

Tests read interface files by name through `tests/ui_sources.py` (`ui_source('composer.js')`,
`ui_stylesheet('panels.css')`), so moving a file between folders does not break them.

Use palette tokens (`--accent`, `--panel`, `--text`, `--muted`, `--border`…) for colours, and
`uiText('…')` with an entry in `locales.json` for any visible text.
