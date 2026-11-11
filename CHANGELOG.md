# Changelog

All notable changes to V-Agent are listed here. Versions follow [Semantic Versioning](https://semver.org/).
Minor updates delivered through the signed components channel are numbered per version:
**1.0.0 C1**, **1.0.0 C2**… They change only the listed parts and never the version number.

## 1.0.0 C1 (minor update)

- Tighter spacing above "Projects" in the sidebar (interface patch).

## 1.0.0 — first public release

- Installer with language selection (es, en, pt, fr, de) and install folder; no administrator rights.
- Hardware detection on first run with an engine recommendation (llama.cpp CUDA, Vulkan or CPU) and a
  verified download of the latest official build; Strata and Strata Rust available from Settings.
- Interactive tour of the interface in the installer's language.
- Signed self-updates from the official repository (Ed25519, newer-version and checksum checks), plus a
  signed components channel for minor updates (MCP servers, tools and interface patches) without a new
  installer.
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
