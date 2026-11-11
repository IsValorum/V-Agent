# V-Agent

**A local-first AI agent for Windows.** V-Agent runs GGUF models on your own PC through the official
**llama.cpp**, **Strata** and **Strata Rust** engines — or connects to any OpenAI- or Claude-compatible
API — and gives them real tools: files, commands, web search, a browser, code checks, projects and MCP
servers, with clear permissions and an isolated workspace per chat.

- **License:** Apache License 2.0 (see [LICENSE](LICENSE), [NOTICE](NOTICE), [third-party notices](THIRD-PARTY-NOTICES.md))
- **Platform:** Windows 10 / 11, x64
- **Languages:** Español, English, Português, Français, Deutsch (chosen in the installer)
- **Privacy:** no telemetry, no account. See [PRIVACY.md](PRIVACY.md).

## Install

1. Download `V-Agent_<version>_x64-setup.exe` from the [Releases](../../releases) page.
2. Choose your language and the install folder. No administrator rights are needed.
3. On first start, V-Agent detects your hardware and recommends an engine:

   | Your hardware | Recommended engine |
   |---|---|
   | NVIDIA GPU with a recent driver | llama.cpp **CUDA** |
   | AMD Radeon RX, Intel Arc, or NVIDIA with an older driver | llama.cpp **Vulkan** |
   | Integrated graphics or no GPU | llama.cpp **CPU** |

   The engine is downloaded from its official GitHub releases (latest version), checked against the
   published SHA-256 digest, tested, and only then activated. Strata and Strata Rust can be installed
   the same way from **Settings → System and engines**.
4. Add a GGUF model (**Model → Add model**) or connect an API, and start chatting. A short interactive
   tour explains every part of the interface; repeat it any time from **Settings → General**.

V-Agent never copies or modifies your model files; it only remembers their path.

## Features

- **Agent modes** — Light, Standard and Full decide how many tools and how much autonomy the agent has.
- **Access and approvals** — work in an isolated folder per chat (sandboxed commands, no network) or
  on the whole PC; approve each action, approve once per chat, or let read-only actions run.
- **Tools** — files with versions and undo, shell commands, web search and page reading, an
  autonomous browser, HTTP requests, system information, Hugging Face, projects, and any MCP server.
- **Code checks on save** — Python, JavaScript, JSON, YAML, TOML, XML/SVG and Java syntax; HTML is run
  in a headless browser and reports runtime errors; Three.js scenes report camera, instances and
  moving parts that intersect static geometry.
- **Recovery** — drafts of interrupted file writes are kept and can be resumed; failed writes get one
  automatic correction attempt; denied actions stop the turn and are never stored.
- **Interface** — glass, soft or Art Deco styles, eight palettes with matching app icons, light/dark
  themes, sliding controls, live performance (tokens/s, context, VRAM/RAM), chat search.

## Updates

V-Agent checks this repository's releases for new versions. An update is accepted only if its
manifest is **signed with the maintainer's Ed25519 key** (the public key is built into the app), the
version is newer than the installed one, and the installer's size and SHA-256 match the signed
manifest. Engines are updated separately from their own official channels.

Smaller fixes (MCP servers, web search, tool descriptions, code checks) arrive through a separate
**components channel**: signed with the same key, tied to the exact app version, limited to a fixed
list of files, re-verified at every start, and removable from **Settings → General**.

## Building from source

Requirements: Windows 10/11 x64, Python 3.13, Rust (stable, MSVC), Node.js, Visual Studio Build Tools.

```bat
python -m venv .venv && .venv\Scripts\pip install -r requirements.txt
scripts\build-desktop.cmd      :: developer build (bundles the local runtime folder)
scripts\build-release.cmd      :: official installer: no engines, no personal data
```

See [RELEASING.md](RELEASING.md) for signing and publishing, [CONTRIBUTING.md](CONTRIBUTING.md) to
contribute and [SECURITY.md](SECURITY.md) to report vulnerabilities.

## Data locations

| What | Where |
|---|---|
| Program | the folder chosen in the installer |
| Chats, settings, downloaded engines, logs | `%LOCALAPPDATA%\V-Agent-Data` |
| Your models | wherever you keep them (never copied) |

Uninstalling keeps your data unless you tick **Delete the application data**.
