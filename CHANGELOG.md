# Changelog

All notable changes to V-Agent are listed here. Versions follow [Semantic Versioning](https://semver.org/).

Minor updates delivered through the signed components channel are numbered per version:
**1.0.1 C1**, **1.0.1 C2**… They change only the listed parts and never the version number.

## 1.0.1 C1 (minor update)

- Tighter spacing above "Projects" in the sidebar (interface patch).

## 1.0.1

- **Modelos** window (sidebar): browse GGUF models on Hugging Face by text or vision, sorted by downloads,
  trend, likes or date; see downloads, likes, architecture, context, parameters and license, the rendered
  model card, and every quant with its size and whether it fits your GPU. Downloads are resumable,
  verified against the Hub's SHA-256 and added to V-Agent automatically.
- Import models from **LM Studio** and **Unsloth Studio** together with their settings (sampling,
  context, KV cache and custom chat template); send V-Agent's settings back to LM Studio, as an Unsloth
  Studio preset, or as a portable settings file.
- One bar: the header above the chat is merged into the sidebar (status, console, browser and theme
  sit in its top row), so conversations start at the top of the window.
- **Projects** section in the sidebar: a single "Projects +" line until you add one, then each project
  with its own chats and a quick "new chat in this project".
- Windows no longer flicker: settings, Modelos, tools, console and model controls use a frosted,
  nearly opaque surface instead of a live blur over their whole area (the blur was recomputed on
  every scroll, image or progress change, which flashed on hybrid-GPU laptops). Small menus, notices
  and the composer keep the real glass blur. (Installer re-published the same day.)
- The signed minor-updates channel can also fix the interface (ui-patch.css / ui-patch.js), so small
  visual fixes arrive as 1.0.1 C1, C2… without a new installer.

## 1.0.0 — first public release

- Installer with language selection (es, en, pt, fr, de) and install folder; no administrator rights.
- Hardware detection on first run with an engine recommendation (llama.cpp CUDA, Vulkan or CPU) and a
  verified download of the latest official build; Strata and Strata Rust available from Settings.
- Interactive tour of the interface in the installer's language.
- Signed self-updates from the official repository (Ed25519, newer-version and checksum checks), plus a
  signed components channel for minor updates to MCP servers and tools without a new installer.
- Agent modes, isolated per-chat workspaces, approvals (once / always in this chat), MCP servers and
  plugins, projects, chat search, file versions and draft recovery.
- Code checks on save for Python, JavaScript, JSON, YAML, TOML, XML/SVG, Java, HTML and Three.js scenes.
- Glass, soft and Art Deco interface styles, eight palettes with matching app icons.
