# Changelog

All notable changes to V-Agent are listed here. Versions follow [Semantic Versioning](https://semver.org/).
Minor updates delivered through the signed components channel are numbered per version:
**1.0.0 C1**, **1.0.0 C2**… They change only the listed parts and never the version number.

## 1.1.8

Release focused on workspace ergonomics, model organization, persistent instructions, and interface polish across all themes and languages.

- **Detailed response metrics and timestamps (`agent/agent.py`, `agent/ui/app/chat.js`, `agent/ui/app/composer.js`):** Every reply shows its total time and a **Details** breakdown (prompt read, cached tokens, generation rate, time to first token, rounds, tool calls, and finish reason) plus the local timestamp next to the model name.
- **Live activity chip, queued follow-ups, and context ring (`agent/ui/app/composer.js`, `agent/ui/app/model-controls.js`, `agent/ui/v-agent.html`):** The composer stays usable while the model replies (`Enter` queues a follow-up, `Ctrl+Enter` redirects the active turn), a live activity chip tracks the current phase and active tool above the composer, and a context ring in the header mirrors context usage at a glance.
- **Temporary chats, pinned chats, date groups, and renaming (`agent/ui/app/conversations.js`, `agent/ui/app/shell.js`):** Start ephemeral chats that are never saved to history (with one-click **Save chat** to keep them), pin favorite chats to the top, browse conversations grouped by date (*Today*, *Yesterday*, *Last 7 days*, *Older*), and rename chats directly from the menu. Archiving a non-open conversation now persists to disk reliably.
- **Persistent instructions (`agent/instructions.py`, `agent/agent.py`, `agent/desktop_runtime.py`):** Global `AGENTS.md` instructions editable in **Settings → General**, automatically combined with any project-level `AGENTS.md` when working inside a project folder.
- **Native non-modal workspace tools (`agent/ui/app/polish.js`, `agent/ui/styles/panels.css`):** Quick switcher (`Ctrl+K`) with category filters, in-conversation search (`Ctrl+F`), prompt library sheet (with one-click save of the current composer text), corner keyboard shortcuts reference (`Ctrl+/`), turn-to-turn navigation (`Alt+↑/↓`), background completion notifications, inline "No model loaded" composer strip, and a local **Usage** telemetry tab in Settings computed strictly from saved real engine figures.
- **Unified model folder layout and safe moving (`agent/model_mover.py`, `agent/model_hub.py`, `agent/ui/app/models.js`):** Models downloaded from the integrated Hugging Face tab or moved from LM Studio / Unsloth Studio / external folders are organized cleanly under `models/<creator>/<model>/` together with split shards, vision (`mmproj`), and MTP companions, with a live progress bar and safe atomic/chunked moves. Already-imported models cannot be re-selected in Import/Export, and Import/Export is hidden when using API providers.
- **Model list, menus, and performance polish (`agent/ui/app/model-controls.js`, `agent/ui/app/shell.js`, `agent/ui/app/chat.js`, `agent/ui/styles/panels.css`):** Starred favorite models, live GPU/RAM fit badges, unified **System & engines** cards (removing the duplicate updates list), stronger visual relief on key buttons and API/engine disclosures, full 5-language translations (`es`, `en`, `pt`, `fr`, `de`), and event-driven UI updates removing idle background polling.

## 1.1.7

Release fixing API connections and updates, reading every statistic from the engine itself, translating the rest of the interface and correcting the GPU memory reported on Windows.

- **GPU memory on Windows (`agent/hardware_stats.py`, issue #1):** `Win32_VideoController.AdapterRAM` is a 32-bit value, so every card with 4 GB or more was reported as 4 GB (a 12 GB Radeon RX 6700 XT read 4095 MiB), shrinking model-fit labels and automatic sizing. The size now comes from the driver's 64-bit `HardwareInformation.qwMemorySize`, or from DXGI when the driver does not write it; WMI is kept only when nothing larger is reported, so integrated GPUs keep their shared memory. The `source` field records which one was used.
- **Statistics from the engine, never estimated (`agent/engine_manager.py`, `agent/desktop_runtime.py`):** llama.cpp sends its own timings on every chunk and the prompt read's progress (`timings_per_token`, `return_progress`); Strata Rust is read from its `/api/stats` (live tokens, and each request's exact read and write times); Project Maya from its `/metrics`. Strata (PolyStrata) now also shows the prompt read's progress. Prompt sizes are no longer estimated from character counts, and streamed chunks are no longer counted as tokens. With an API, the provider's own counts are used (Claude reports the input at the start), the output speed is measured as received, and the wait before the first token is no longer shown as a reading speed.
- **Exact tool cost:** The token cost of the enabled tools (*Settings*) is counted by the engine or provider (llama.cpp `/apply-template` + `/tokenize`, Maya `/tokenize`, Strata Rust and Claude `count_tokens`, Strata's own tokenizer and template). It is marked as estimated only on OpenAI-compatible APIs, which have no counting endpoint.
- **"Use model" with an API did nothing:** A KV-cache setting left over from a local engine was sent with the API model, the core refused it and the button failed silently. API models now ignore local-only settings, and a failed save is reported.
- **Updates with an API model:** Engine and app updates no longer ask to unload an API model (only a model loaded in local memory blocks them). Installing an engine right after a restart checks for the release first instead of failing.
- **OpenCode plans (`agent/remote_protocols.py`, connection form):** Separate presets for **OpenCode Go / Go Plus** (one endpoint; the plan comes from the key) and **OpenCode Zen** (account balance; its free models only work inside the OpenCode app). The current `https://opencode.ai/inference` endpoints are supported with their per-protocol paths, and OpenCode always uses `Authorization: Bearer`.
- **Translations (`agent/ui/locales.json`, `agent/ui/standalone/i18n.js`):** Over 300 interface, status and error messages from the core added in English, Portuguese, French and German, including update notices. Messages with values (paths, counts, models) are translated through templates, and "prefix: detail" and multi-sentence messages part by part. The language audit now also fails on Spanish that is missing from the catalog.

## 1.1.6

Release making the terminal tools usable by any model without a harness-specific fine-tune: Linux habits are explained instead of failing silently, output is clean, background jobs and servers behave, and nothing changes what a working program does.

- **Clean, non-interactive console (`agent/shell_hygiene.py`, `agent/pc_mcp.py`, `agent/sandbox_exec.py`):** Every command runs without colours, prompts or pagers (`NO_COLOR`, `GIT_TERMINAL_PROMPT=0`, `PIP_NO_INPUT`…) and with unbuffered Python output. `CI`, `PYTHONUTF8` and `PAGER` are deliberately not set, since they change what users' programs do. Output is cleaned the way a person reads a terminal: escape codes removed, carriage-return progress bars collapsed to their final state, padding stripped, repeated lines summarised, PowerShell CLIXML errors made readable, the console's old code page and UTF-16 decoded line by line, and binary output replaced by one line.
- **Several lines actually run:** `cmd /c` ran only the first line of a multi-line command and reported success; such commands now run as a batch script with the last exit code.
- **Bash habits explained:** A note is added even on success for single quotes, `$VAR`, `;`, `/dev/null`, `-x` options on cmd built-ins, `%%i` in batch `for` loops, and `find`/`timeout` when this PC really runs the Windows programs of that name. Failures get a hint for `ls`/`cat`/`grep`/`rm`/`export`…, `./script`, `python3`, `mkdir -p`, `NAME=value cmd`, prompt signs and markdown fences, PowerShell `&&` and `curl`, missing keyboard input, Git credentials and timeouts.
- **Background jobs and servers:** A trailing `&` or `nohup` is refused at once (it blocked the call until its time limit) with the way to run it in the background. `job_wait` takes `until` and returns as soon as a server prints its ready line, or when the job goes quiet. Jobs keep their latest output in a rolling buffer, and each check returns only what is new. The last lines are no longer lost when a job ends.
- **Long output:** The beginning and the end are shown; the whole output (up to 4 MB) is saved to `outputs/` for `fs_read`.
- **Tool description the model actually receives (`agent/mcp_prompt.py`):** It now states the cmd quoting, variables and separators, the configured time limit, and how to run servers. The description in `pc_mcp.py` was always replaced by an older one.
- **Engine cleanup:** Old engine folders briefly locked by antivirus right after an update are retried instead of left until the next start.
- **Tests:** `tests/test_shell_hygiene.py` (`30` cases, including real commands and background jobs). A small real model on `llama.cpp` completed console tasks that previously failed or stalled for over 10 minutes.

## 1.1.5

Release aligning provider error handling with the open-source agent harnesses (OpenCode, Goose, Roo Code, Cline, Aider), so a busy provider no longer ends an autonomous run. Includes the 1.1.4 C1 fixes.

- **Retry policy (`agent/agent_resilience.py`, `agent/agent.py`):** Busy or throttled providers (HTTP 408/409/425/429, 5xx, 529 "Overloaded", dropped streams) are retried 10 times with exponential waits of 2, 4, 8, 16 then 30 s and ±20 % jitter (about 3.5 minutes), never shorter than the provider's `Retry-After` / `retry-after-ms` (capped at 15 min). With no network path (DNS or route failures) retries continue for up to an hour; timed-out attempts are retried at most 3 times. Exhausted balance or quota (402, `insufficient_quota`/balance on 429) and other rejected requests stop at once. A 429 worded like an overflow is treated as a throttle.
- **Empty replies:** A reply with no text, no reasoning and no tool call is repeated (twice at most), as Cline and Roo Code do.
- **Provider errors keep their status (`agent/engine_manager.py`):** `ProviderHTTPError` carries the HTTP status and the requested wait; new plain-language hints for 402 (no balance), 503 and 529 (provider overloaded).
- **Output limit as OpenCode computes it:** The catalog's output maximum, 32,000 when the provider does not declare one, never above 256,000, fitted to the room left in the window with 15 % estimate error and 1 % headroom (minimum 1,024).
- **Translated provider errors (`agent/ui/standalone/i18n.js`):** "Provider error (N): …. Detail: …" is translated part by part into `en`, `pt`, `fr` and `de`; retry cards cover no-connection and empty-reply cases.
- **From 1.1.4 C1:** *Render HTML* works on pages with a `<canvas>` again (3D/voxel scene diagnostics), and the composer has a double edge with a clear gap.
- **Tests:** `tests/test_agent_resilience.py` covers the new classes, schedule, jitter and `Retry-After`; `tests/test_remote_providers.py` checks the status and `Retry-After` of a real 529 response and the output limits; `tests/smoke/agent_autonomy_ui.py` adds an empty reply and an exhausted balance (`14/14`).

## 1.1.4

Fix release: API models no longer run out of output inside their reasoning, a reasoning-only round is followed by action instead of an empty reply, and the remaining untranslated interface text is translated.

- **"No limit" means the model's own output maximum (`agent/engine_manager.py`, `agent/remote_protocols.py`):** With no output limit set, V-Agent used to omit `max_tokens`, so providers applied their own small default and long reasoning used it all, ending the reply empty. Requests now carry the model's declared output maximum (also read from `max_completion_tokens` / `top_provider` / `limits.output`), or 65,536 when the provider does not declare one, kept within the window left by the prompt. A provider that refuses the value gets the request again without it, remembered per model. How much the model thinks is still set only by the thinking effort.
- **Reasoning-only rounds (`agent/agent.py`, `agent/ui/app/composer.js`):** A round that ends with reasoning but no reply and no tool call is asked to act (up to twice) instead of ending the turn; if nothing comes, a clear translated message says what happened instead of "the model finished without returning text".
- **Translations (`agent/ui/app/chat.js`, `agent/ui/app/composer.js`, `agent/ui/app/shell.js`, `agent/ui/v-agent.html`):** "Reasoning…", the live-arguments label, truncated-result notes and the screen-reader names of the page regions are now translated into `en`, `pt`, `fr` and `de`.
- **Tests:** new `tests/smoke/ui_language_audit.py` drives the real interface through every live state of a reply in each language and fails on Spanish left on screen; `tests/smoke/agent_autonomy_ui.py` adds the reasoning-only round and the output maximum sent to the provider; `tests/test_remote_providers.py` covers the output maximum and its fallback.

## 1.1.3

Release making long autonomous runs survive provider errors and full context windows, letting the agent ask the user mid-task, and strengthening the code checker.

- **Ask the user mid-task (`agent/ask_user.py`, `agent/agent.py`, `agent/ui/app/shell.js`, `agent/ui/app/chat.js`):** New built-in `agent__ask_user` tool for every engine (local and API providers) when the request comes from the interface. The model asks one short question with up to 4 options; the user picks one, types an answer, or lets the agent decide. At most 3 questions per turn; after 15 minutes without an answer the agent continues on its own judgment and states its assumptions. Tool instructions are in English; the dialog and cards are translated into `en`, `pt`, `fr` and `de`.
- **Automatic retries (`agent/agent_resilience.py`, `agent/agent.py`):** Transient engine/provider failures in the middle of a turn (HTTP 408/429/5xx/529, dropped connections, replies cut before their end mark) repeat the round up to 3 times (2, 6 and 15 s), shown as an "Automatic retry" card; authentication, bad-request and missing-model errors still stop the turn.
- **Context kept within the window during long turns:** Past 60 % of the model's window, old tool batches are archived to the chat's `context/` folder and old outputs shortened; when the engine still refuses a prompt as too long, the history is shortened further and the round repeated. Shown as a "Context trimmed" card.
- **Stronger `code_check` (`agent/code_insight.py`, `agent/verify.py`, `agent/pc_mcp.py`):** Python adds `pyflakes` static analysis (undefined names, locals used before assignment, unused imports) and flags imported modules missing from the user's Python; HTML reports missing local scripts/styles/frames as errors, plus duplicate ids and script lookups of ids the page lacks; CSS `url(...)` and JavaScript relative `import`/`require` targets that do not exist are reported. Results also appear in the write-time check.
- **Dependencies:** `pyflakes 3.4.0` (MIT) bundled.
- **Tests:** new `tests/test_agent_resilience.py`, `tests/test_code_insight.py` and `tests/smoke/agent_autonomy_ui.py` (real interface against a scripted local provider: question with options, "let the agent decide", a mid-turn 503 and a context overflow).

## 1.1.2

Fix release: buttons that did nothing when clicked now act or say why.

- **"Use model" with an API (`agent/ui/app/model-controls.js`, `agent/ui/app/composer.js`, `agent/ui/app/controls.js`):** The visible button now loads or releases the model itself instead of pressing a hidden button whose enabled state was computed elsewhere. A local `llama.cpp`/`Strata` load still marked as "preparing" in the core (stuck or left over, for up to 15 minutes) no longer blocks provider models: "Use model", "Disconnect API" and sending messages work. A leftover "preparing" state is checked with the core and cleared.
- **No more silent clicks (`agent/ui/app/shell.js`, `agent/ui/app/settings.js`, `agent/ui/app/events.js`, `agent/ui/app/load-settings.js`, `agent/ui/app/models.js`):** During a reply or an engine operation, file access, approvals, "Add files", "Refresh", "Reconnect MCP", "Add model" and the draft model's "Choose…" now say why they cannot act instead of ignoring the click. After a download or import the model list refreshes even while a reply is running.
- **Translations:** The new messages are translated into `en`, `pt`, `fr` and `de`.
- **Tests:** `tests/smoke/api_use_model_ui.py` drives the real interface against a local fake provider (no account) and fails on 1.1.1 in all five reported cases.

## 1.1.1

Release introducing optional Project Maya integration, custom pre-compiled build support across all four local engines, per-model engine load options, an intermediate installer progress window on app updates, engine uninstall, and `llama.cpp` update reliability fixes.

- **Optional Project Maya (`mw00/project-maya`) integration (`agent/maya_engine.py`, `agent/engine_manager.py`, `agent/thinking_policy.py`):** Added optional local engine support with Windows CUDA 13.2+ / VS 2026 and AMD ROCm prerequisite inspection, GitHub tag auto-updating, and per-family configuration (`GLM-5.3-Flash`, `GLM-5.3 744B`, `DeepSeek-V4.1-Flash-1017`, `MiniMax-M3.1-Flash`, `Qwen-3.8-Flash-Next`) without forcing installation in onboarding or settings.
- **Custom build selection for all 4 local engines (`agent/engine_manager.py`, `agent/maya_engine.py`, `agent/runtime_paths.py`, `agent/model_import.py`, `agent/kv_settings.py`, `agent/ui/app/engine-controls.js`):** Users with their own pre-compiled `Strata · PolyStrata`, `Strata Rust`, `llama.cpp`, or `Project Maya` binaries can select them directly without forced downloads or recompilation, preserving custom paths across variant switches and prepending companion DLL directories on launch.
- **Per-model engine load options (`agent/engine_options.py`, `agent/ui/app/load-settings.js`):** Added a `--help`-filtered catalog of engine load flags for `llama.cpp`, `Strata`, and `Strata Rust` with conflict validation (e.g., quantized KV cache requiring Flash Attention) and per-model persistence.
- **Installer progress mini-window (`agent/app_updates.py`, `agent/ui/app/tour.js`, `agent/ui/styles/panels.css`, `agent/desktop_runtime.py`):** Added an in-app transition overlay and an external WinForms progress mini-window during **Install and restart** (English default, localized to `en`, `es`, `pt`, `fr`, and `de`) so users never see a blank screen while the installer runs and V-Agent restarts.
- **`llama.cpp` update fix, engine uninstall, and update storage cleanup (`agent/engine_updates.py`, `agent/components.py`, `agent/app_updates.py`):** Fixed `llama.cpp` updates getting stuck at 100% downloaded without installing (handling transient `WinError 32` file locks and resetting progress cleanly), added clean engine uninstall/unlinking, and pruned superseded component revisions and already-installed/broken installers.
- **5-language UI coverage & fast-extraction packaging:** Updated `1,899` translated phrases across `es`, `en`, `pt`, `fr`, and `de` in `agent/ui/locales.json` and `i18n.js`, built from a verified clean Git worktree using fast `zlib` NSIS decompression.

## 1.1.0

Release focused on cleaner tool-execution UI, automatic minor updates without manual intervention, optional local engine setup on fresh installs, hardened remote API compatibility, and clearer MCP parameter diagnostics.

- **Collapsible tool execution trace:** Tool calls during assistant runs now group inside a `<details class="tool-trace-group">` container that starts collapsed by default, with an accessible toggle summary and individually expandable `<details class="tool">` entries for inspecting arguments, durations, and outputs without cluttering the conversation.
- **Automatic minor component updates:** Minor updates (`components`) now check automatically shortly after startup (`1.5 s`), retry transient GitHub/network errors with progressive backoff (`20 s` to `300 s`) instead of sleeping for hours, fetch up to `100` releases per page with explicit signed-manifest validation, and hot-reload UI patches into the active window cleanly while emitting `v-agent-components-update`.
- **Optional local engines on first run:** Onboarding step 2 lets new users configure a remote API or skip local engine installation instead of forcing `llama.cpp` or `Strata Rust` downloads up front; update stacks no longer push install banners for engines that are not installed, and missing-engine errors clearly distinguish `Strata Rust` from `llama.cpp`.
- **Hardened remote API protocol support and UI controls:** Added `agent/remote_protocols.py` and per-connection UI controls (`engine-controls.js`) covering `V-Agent/<version>` global `User-Agent` (with per-provider override and `X-Stainless-*` removal), CRLF and Latin-1 header validation, provider presets and auth modes (`auto`, `openai`, `anthropic` `x-api-key` + `anthropic-version` + `anthropic-beta`, `azure` `api-key` + `api-version` + classic `/openai/deployments/` 404 fallback, `opencode` persistent per-conversation UUID v4 `x-opencode-session` across turns/compaction, and `openrouter` `HTTP-Referer` / `X-Title` / `delta.reasoning` / SSE comments), plus SSE anti-buffering headers (`Accept: text/event-stream`, `Cache-Control: no-cache`, `Accept-Encoding: identity`) and transparent `gzip`/`deflate` fallback decoding.
- **MCP diagnostic improvements:** Improved `pc` MCP `KeyError` messages to identify the missing required argument cleanly, alongside updated remote-provider, UI, update-channel, and MCP recovery test coverage.

## 1.0.9

Major release featuring a full UI redesign, major MCP and document-reading upgrades, English-only model-facing MCP standardization, accurate VRAM/GGUF memory estimation, and integrated browser/search fixes.

- **Redesigned interface and refined Art Deco appearance:** Streamlined the top bar, composer controls,
  unified model selector card, tabbed Load/Generation settings, and typography; softened Art Deco geometry
  with stepped corner ornaments and double-line trim (`Art Deco` in the English style picker); and moved
  the collapsible `Memory breakdown` panel directly inside the Context card.
- **English-only model-facing MCP standardization:** Converted remaining Spanish MCP tool errors, validation
  messages, workspace/sandbox hints (`pc`, `duckduckgo`, `AccessPolicy`, `draft_recovery`), `find_in_page`
  notices, and context-compaction prompts (`conversation_codec`, `agent`, `engine_manager`) to clear English
  for reliable multi-step tool execution across local and remote models.
- **Built-in document reader (`pc__doc_read`) and remote document extraction:** Added `pc__doc_read` to
  extract text, tables, and metadata from PDF (with Windows OCR fallback for scanned pages), Word (`.docx`),
  Excel (`.xlsx`/`.xlsm`), PowerPoint (`.pptx`), OpenDocument (`.odt`/`.ods`/`.odp`), EPUB, RTF, HTML, XML,
  and CSV files with `pages` range selection and `mode` (`auto`, `markdown`, `text`, `tables`); `pc__fs_read`
  detects formatted/binary documents and directs models to `doc_read`, `pc__doc_read` is registered across
  read-only safety/approval/profile rules, and `duckduckgo__web_visit` downloads and extracts remote documents
  up to 24 MiB (and web pages up to 8 MiB).
- **Removed artificial MCP truncation caps and added Documents options:** Expanded `MCP Options` so
  `duckduckgo` `visit_tokens` scales from `0` (unlimited) to `1,000,000` (previously capped at `2,000`),
  changed `duckduckgo` `max_result_chars` default from `12,000` to `0` (`unlimited`, `0–1,000,000`) while
  removing the internal `11,500`-character clamp in `web_visit`, raised `pc` and `hf` `max_result_chars`
  ceilings to `1,000,000`, and added a dedicated `documents` settings section (`extract_mode`, `max_pages`,
  `max_chars`, `include_tables`, `ocr_scanned`, `include_metadata`).
- **DuckDuckGo search fallback and local compaction hardening:** `duckduckgo__web_search` treats clean
  `No results found` responses (including regional or Yahoo queries) as empty searches rather than server
  outages, retries without quotes when quoted queries yield no hits, and falls back to the `wt-wt` global
  region on empty regional results; local context compaction strips `<think>` blocks on Strata, llama.cpp,
  and Strata Rust.
- **Accurate VRAM warnings and GGUF memory estimation:** Hides the llama.cpp offload warning when running
  Strata or Strata Rust, accounts for reclaimable VRAM already held by the active llama.cpp server to avoid
  false overload warnings when enough free VRAM exists, and extends `memory_estimate` and `gguf_catalog`
  for sliding-window attention (`SWA`), MLA/LoRA KV, shared KV layers, and recurrent/SSM/KDA/ShortConv states.
- **Integrated browser, search toggle, and desktop window fixes:** Added a fullscreen toggle to the integrated
  browser dock, upgraded the web search toggle to a high-contrast globe-and-magnifier icon with a
  theme-adaptive `WebSearch/WebVisit` tooltip, opens release notes in an in-app dialog instead of inside the
  browser dock, and fixed sandbox/conversation folder opening and native save dialogs for chat and theme
  exports.
- **Complete UI translations, loading feedback, and clean release pipeline:** Stabilized the `Tools` counter
  and standardized `Tools` across all 5 languages (`es`, `en`, `pt`, `fr`, `de`), made the model loading
  progress bar adapt to every theme and accent color, completed remaining help-card and loading-phase
  translations (`Shared console`, `MTP`, preparation states), and enforced clean-worktree release builds that
  verify runtime binaries and exclude personal data or development artifacts.

## 1.0.8

- **Provider models with very long context can be used.** "Use model" on an API model that declares more
  than 262,144 tokens (for example DeepSeek V4.1 Flash, 1,048,576) failed with "context out of range":
  the local engines' limit was applied to remote models, and their preferences could not be saved either.
- **Switching between provider models works.** With one API model in use, "Use model" on another stayed
  disabled without a word; it now switches at once (a provider model is only a selection). Changing API
  connection or engine no longer asks to "unload" a provider model first.
- **A provider reply cut half way is reported** instead of being shown as a complete answer.
- **Provider errors in plain words:** what the code means (invalid key, usage limit, provider down…) and
  the provider's own message, never its HTML page or raw JSON; the key stays hidden.
- No more absurd speeds (tens of thousands of tokens per second) for replies a provider delivers in one burst.
- **Native context compaction button & endpoints.** Added a "Compact context" control in the model panel
  backed by `/api/harness/context/compact` and `/api/context/compact`, using OpenAI `/responses/compact`
  with `/chat/completions` fallback, Anthropic `/messages`, or the loaded local engine, and preserving
  compacted checkpoints across follow-up turns.
- **Reliability fixes across all 7 bundled MCP servers** (`pc`, `autobrowser`, `computer`, `admin`, `hf`,
  `duckduckgo`, `web`): prevents `job_status` deadlocks, captures Shadow DOM and nested iframe text, uses
  CDP `DOM.setFileInputFiles` for file inputs, reports failed network requests and navigation errors,
  validates HTTP redirects while preserving existing files on failed downloads, returns structured syntax
  diagnostics in `code_check`, avoids elevation prompts in `admin` `status`, and normalizes schemas for
  small (4B–8B) and frontier models.
- **Engine, `serve/` and interface fixes:** strips `api--` prefixes reliably during context compaction,
  emits mid-stream SSE errors on HTTP 200 instead of broken 503 responses, synchronizes `ReplicaPool`
  health recovery and telemetry counters, enforces strict JSON object validation, and keeps UI panel rules
  and 1,265 translated phrases consistent.

## 1.0.7

- **"Automatic" never asks.** In the Light profile, console commands, shell commands and code runs still
  asked for approval with "Automatic" selected, without saying why.
- **"Confirm changes" lets reads through, as it says.** It asked before searching files and listing a
  file's versions (which "Ask every time" allowed), before reading the status of approved background
  jobs and before reading the page the agent's own browser has open.
- **The context meter moves live with Strata Rust.** Its count started from zero, showed only the
  generated tokens and jumped back and forth between rounds; it now starts from the prompt (estimated
  when the request is sent, corrected with the exact count after each round). With every engine the meter
  no longer steps backwards between tool rounds.
- **No more files piling up in a chat's folder.** Every tool call, even a listing or a read, left a JSON
  file in `drafts/`, and every written file a full copy. Only an unfinished file write is kept now, the
  only thing that can be recovered; old leftovers are removed when the chat is opened.
- The tool and market windows no longer show tool servers as "starting" right after V-Agent opens.

## 1.0.6

- **"Install and restart" is much faster.** Measured on a laptop, the ~25 s restart went into three
  things: unpacking the 540 MB program from a solid LZMA installer (~12 s), the core waiting for every
  tool server and an engine probe before answering the window (~5 s), and fixed pauses. Now the installer
  uses zlib (unpacks in ~2 s; the download is somewhat larger), the core answers the window in ~1.7 s
  and starts the tool servers in the background (the first reply waits for any still starting), the
  NVIDIA hardware profile is read from the driver library instead of a separate process, and the window
  closes for the update after 0.3 s instead of 1.2 s. The installer change applies already when updating
  to 1.0.6; the shorter close applies from 1.0.6 on.
- Includes the 1.0.5 C1 fix (windows without a live blur).
- **Replies come in the language you wrote in.** The English article "a" was counted as Portuguese, so a
  plain English request could look ambiguous and the model answered in the language of the tool results.
- **The model window shows the context the engine really runs with** when the model was loaded or resized
  from outside the window (the API or another client); it showed the saved preference instead.
- **Adding a model with Strata Rust active** used Strata's importer: it answered with an id Strata Rust
  does not list (so the model could not be loaded by that id) and refused architectures that only Strata
  cannot run. Adding a GGUF now follows the active engine.
- A chat request whose `messages` is not a list of messages gets a clear 400 instead of a 503.
- Quality tools in the repository: real-model runs on the three engines, screen-versus-core checks, XSS
  attacks on model cards, per-language checker battery, static analysis and release verification, with
  a results report per version in `docs/test-reports/`.

## 1.0.5 C1 (minor update)

- **Windows no longer flicker.** Large windows (model & generation, tools, settings, models) had a live
  26 px blur again: the glass rule listed them together with a more specific selector, which beat the
  no-blur rule meant for windows, so every repaint behind a window recomputed the blur. Windows now get
  the frosted, nearly opaque surface; menus, notices and the composer keep the blur.

## 1.0.5

- **Strata Rust: a model counts as loaded only once it really is.** Strata Rust lists the model it is still
  loading, so V-Agent marked a model as ready that the engine then refused (for example a Gemma 4 model,
  which Strata Rust does not run) and the next message failed with "WinError 10061". V-Agent now waits for
  the engine's own "loaded" line, says in plain words which architectures the engine runs, and if an engine
  closes after loading, the chat says so instead of showing a Windows error.
- Strata Rust gets the same private per-session key as llama.cpp (kept out of the process list).
- **Simpler model window.** One model card on top: the name opens the list, choosing closes it and the card
  confirms the choice at once, its state reads "In memory / Not loaded / Loading…" and a single main button
  loads, unloads or switches to the chosen model. The context sits right under it with the estimated memory
  (it was about 1,100 px down the panel), "Apply and reload" appears only when it is needed, and the
  technical settings are folded under "Advanced". The old second pair of load buttons is gone.
- **Switching engine keeps the chosen model** (the same file under the new engine's name) instead of
  loading the first one in the list.
- **The context meter follows the engine:** it no longer blanks out when a message is sent, it shows the
  new limit right after "Apply and reload", it trusts the limit the engine reports, and it moves during
  replies with Strata Rust and APIs too (it showed the previous reply's numbers).
- **Settings follow the model file across engines:** context, sampling, reasoning and rounds chosen for a
  model under llama.cpp are used under Strata Rust too (engine-specific KV and load settings are not copied).
- **Clear messages instead of raw logs:** a GGUF that does not load says why in one line (a damaged tensor,
  out of memory…); an API that cannot be reached says so in plain words instead of "<urlopen error …>".
- **The memory warning is visible:** "the full model does not fit in free VRAM" now appears under the
  context control instead of only inside the folded estimate.
- **Consistent state everywhere:** turning web search off in the Tools window also turns the composer's
  search button off; a refused engine change puts the selector back on the active engine and says to
  unload the model first; a stopped reply keeps its last context measure; API mode no longer shows the
  local model's context block; expert-cache rows are hidden for engines that do not report them.
- **Reading speed is always explained:** Strata Rust and APIs get measured speeds, and a reply read almost
  entirely from the prompt cache says "Reading: from cache" instead of showing nothing.

## 1.0.4

- **Error detection matches the preview.** Pages are checked under the same isolation as V-Agent's
  preview (sandboxed iframe without same-origin), so `localStorage`, cookies or IndexedDB used without
  a fallback are reported instead of "0 errors"; page errors now include their line.
- **More languages checked.** Python is compiled (catches `return`/`await`/`break` in the wrong place);
  JavaScript is checked in the bundled browser when Node.js is not installed; CSS structure and
  PowerShell (Windows' own parser) are checked; TypeScript, C/C++, Rust, Go, PHP, Ruby, Lua and sh use
  their compiler when installed, and say "not checked" otherwise.
- **Engine updates keep two versions** (active and previous, for "Restore previous") instead of every
  version ever installed, delete downloaded archives after extracting them (837 MB on a test PC), reuse
  llama.cpp's unchanged CUDA runtime (373 MB) instead of downloading it again, and remove failed downloads.
- **Updater:** a verified installer is reused instead of downloaded at every start and old installers are
  removed; "Install and restart" also works when a core from an earlier session is still running; a
  check no longer interrupts a running download; the progress poll can no longer freeze.
- **Lower background cost:** GPU readings use NVIDIA's driver library (about 1 ms) instead of starting
  `nvidia-smi` every 5 s (about 60 ms each); the window polls every 20 s instead of 2.5 s while hidden;
  release notes are fetched only when opened; engine logs are capped at 8 MB.
- **Security (audit):** the local server now refuses requests that name another host (DNS rebinding:
  a web page could read saved conversations through 127.0.0.1); llama.cpp's own server gets a private
  per-session key, so web pages cannot use the GPU or read its slots; restoring a file version
  (`file_history` with `revision`) now asks for approval in "Ask" mode, and sensitive file names are
  checked in every path argument (copy and move included).
- **Strata compatibility is asked to the engine itself.** A model whose architecture the installed
  Strata does not run is refused at once with a clear message (it took three restarts and ~45 s, with an
  English error); the answer is cached per engine build and model file.
- **Clearer messages:** a reply cut by the loop guard says why, without asking to "press Save" when
  nothing was being written; a second chat while another is replying says so.
- Pillow is declared (screen-capture tools); a clean build environment left them out silently.
- **A fresh install can work right away:** file, system and web-search tools start enabled, as the
  Standard mode describes (only the browser was on, so a new agent could not create a file). Writes
  still ask in "Ask" mode; console and commands stay off.
- **The date note no longer ends up in files:** it is labelled as a system note and removed if a model
  copies it to the end of a file it writes.
- **Interface:** the built-in browser floats over the chat when the window is too narrow instead of
  squeezing it into a column; buttons and labels use one size per page (several were left at 14 px);
  the same close button in every window; dismissing an update notice shows the next one instead of
  leaving a lone "N more updates" row; Windows 11 is no longer shown as Windows 10; engine
  recommendations are translated (they were English in every language); "No chats" and the engine name
  follow a language change; parameter counts read "9.2B"; the history buttons no longer touch.
- **The core ends with its window.** If the window crashes or is ended from Task Manager, the core and
  the engine it started no longer stay in memory.
## 1.0.3

- Fix installing and restarting after a signed update. The updater waits for the app to close, installs silently, verifies the installed version and restarts it.

## 1.0.2

- Fix model registration and startup with downloaded Strata engines on clean installations.
- Import and export model settings from the model selector for Strata, Strata Rust and llama.cpp.
- Show signed V-Agent updates in a persistent notification; refresh checks while the app is open.
- Add a desktop uninstall entry and locate the vision encoder next to the active Strata engine.
- Refine the model import dialog and avoid duplicated engine versions.

## 1.0.1

- **Fix — models now create files instead of only printing code.** V-Agent tells the model, in one
  short rule, that it works inside a folder and must create/edit files with its tools and verify them.
  Before, a 35B MoE with a template saying "if no function call is needed, answer directly" wrote the
  page into the chat and never called `fs_write` (same model and request: 0 tools before, `fs_write` +
  `code_check` after).
- **llama.cpp loading per model:** *Automatic* uses llama.cpp's `--fit` with GPU layers left to it and
  an optional VRAM margin (`--fit-target`); *Custom* turns `--fit` off and sets GPU layers (`-ngl`) and
  MoE experts kept in RAM (`--n-cpu-moe`) by hand. The memory estimate follows both.
- **File tools fixed after a real-model battery:** moving or copying no longer deletes the destination when the source is missing (replacements are staged and swapped atomically); search finds files in the top folder again; the version history shows a preview of each version so the right one is restored; if you ask for a named file and the model only shows code, it gets one more round to write it.
- Minor updates C1 and C2 of 1.0.0 are included.

## Source (not a release)

- The interface is no longer one 5,900-line `index.html`: its source is split by topic in
  `agent/ui/` (`v-agent.html` skeleton, `styles/`, 21 program files in `app/`, `standalone/`) and
  `scripts/build-ui.py` assembles it. The assembled page is the same as before, so nothing changes
  for people using V-Agent.

## 1.0.0 C2 (minor update)

- Tabs are at least as wide as their label, so longer texts ("Importar y exportar", "Importer et
  exporter"…) no longer spill out of the sliding pill.
- Segmented controls measured while their window was closed (Model & engine → "On this computer /
  APIs") show their selection again.
- Includes C1.

## 1.0.0 C1 (minor update)

- Tighter spacing above "Projects" in the sidebar (interface patch).

## 1.0.0 — first public release

- Installer with language selection (es, en, pt, fr, de) and install folder; no administrator rights.
- Hardware detection on first run with an engine recommendation (llama.cpp CUDA, Vulkan or CPU) and a
  verified download of the latest official build; Strata and Strata Rust available from Settings.
- Interactive tour of the interface in the installer's language.
- Signed self-updates from the official repository (Ed25519, newer-version and checksum checks), plus a
  signed components channel for minor updates (MCP servers, tools and interface patches) without a new
  installer. Shortly after starting, V-Agent applies the newest minor update by itself and downloads a
  newer installer if there is one (installing it still asks first), so a fresh install always ends up
  on the latest release.
- **Modelos** window: browse GGUF models on Hugging Face by text or vision, sorted by downloads, trend,
  likes or date; see downloads, likes, architecture, context, parameters and license, the rendered model
  card, and every quant with its size and whether it fits your GPU. Downloads are resumable, verified
  against the Hub's SHA-256 and added to V-Agent automatically.
- Import models from **LM Studio** and **Unsloth Studio** together with their settings (sampling,
  context, KV cache and custom chat template); send V-Agent's settings back to LM Studio, as an Unsloth
  Studio preset, or as a portable settings file.
- One bar: the header lives in the sidebar, so conversations start at the top of the window.
- **Projects** section in the sidebar: a single "Projects +" line until you add one, then each project
  with its own chats and a quick "new chat in this project".
- Agent modes, isolated per-chat workspaces, approvals (once / always in this chat), MCP servers and
  plugins, chat search, file versions and draft recovery.
- Code checks on save for Python, JavaScript, JSON, YAML, TOML, XML/SVG, Java, HTML and Three.js scenes.
- Glass, soft and Art Deco interface styles, eight palettes with matching app icons. Large windows use a
  frosted surface (no live blur) so they never flicker.
