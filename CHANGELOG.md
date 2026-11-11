# Changelog

All notable changes to V-Agent are listed here. Versions follow [Semantic Versioning](https://semver.org/).

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
