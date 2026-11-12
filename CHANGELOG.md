# Changelog

All notable changes to V-Agent are listed here. Versions follow [Semantic Versioning](https://semver.org/).
Minor updates delivered through the signed components channel are numbered per version:
**1.0.0 C1**, **1.0.0 C2**… They change only the listed parts and never the version number.

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
