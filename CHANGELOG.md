# Changelog

All notable changes to V-Agent are listed here. Versions follow [Semantic Versioning](https://semver.org/).
Minor updates delivered through the signed components channel are numbered per version:
**1.0.0 C1**, **1.0.0 C2**… They change only the listed parts and never the version number.

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
