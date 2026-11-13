# Changelog

All notable changes to V-Agent are listed here. Versions follow [Semantic Versioning](https://semver.org/).
Minor updates delivered through the signed components channel are numbered per version:
**1.0.0 C1**, **1.0.0 C2**… They change only the listed parts and never the version number.

## 1.0.9

- **Redesigned interface and refined Art Déco appearance:** Streamlined the top bar, composer controls,
  unified model selector card, tabbed load/generation settings, and typography; softened Art Déco geometry
  with stepped corner ornaments and double-line trim (renamed cleanly to `Art Déco` in the style picker);
  and moved the collapsible `Memory breakdown` (`Desglose de memoria`) directly inside the Context card.
- **Accurate VRAM warnings and GGUF memory estimation:** Hides the llama.cpp offload warning when running
  Strata or Strata Rust, accounts for reclaimable VRAM already used by the active llama.cpp server to avoid
  false overload warnings when enough free VRAM exists, and extends `memory_estimate` and `gguf_catalog`
  for sliding-window attention (`SWA`), MLA/LoRA KV, shared KV layers, and recurrent/SSM/KDA/ShortConv states.
- **Built-in document reader (`pc__doc_read`) and expanded tool limits:** Extracts text, tables, and
  metadata from PDF (including OCR fallback for scanned pages), Word (`.docx`), Excel (`.xlsx`/`.xlsm`),
  PowerPoint (`.pptx`), OpenDocument (`.odt`/`.ods`/`.odp`), EPUB, RTF, HTML, XML, and CSV/TSV files,
  with raised/configurable MCP visit-token and result limits.
- **Integrated browser, search, and desktop window fixes:** Added a fullscreen toggle to the integrated
  browser dock, upgraded the web search toggle to a high-contrast globe-and-magnifier icon with a
  theme-adaptive `WebSearch/WebVisit` tooltip, added DuckDuckGo retry fallback when quoted or Yahoo search
  queries return `No results found`, opens release notes in an in-app dialog instead of inside the browser
  dock, and fixed sandbox/conversation folder opening and native save dialogs for chat and theme exports.
- **Complete translations, loading feedback, and clean release pipeline:** Stabilized the `Tools` counter
  and standardized `Tools` across all 5 languages (`es`, `en`, `pt`, `fr`, `de`), made the model loading
  progress bar adapt to every theme and accent color, completed remaining help-card and loading-phase
  translations (`Shared console`, `MTP`, preparation states), normalized model-facing prompts/errors, and
  added clean-worktree release builds that verify runtime binaries and exclude personal data or dev artifacts.

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
