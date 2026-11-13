# How V-Agent is tested

V-Agent runs models and tools on your own PC, so it is checked at several levels: unit tests on every
push, static analysis, runs with real models, an automated walk through the whole interface, and
checks of every release before and after it is published. This page lists what each level covers,
which areas are reviewed for security, and what is still not covered.

| Level | What it catches | Where |
|---|---|---|
| Automatic tests | Regressions in the core and the interface logic | `tests/`, run on every push by GitHub Actions |
| Static analysis | Undefined names, unreachable code, unsafe patterns | ruff, bandit, ESLint (below) |
| Real-model runs | What only shows up when a model drives the tools | `tests/smoke/` |
| Interface walk-through | Screens that look wrong, state the screen and the core disagree on | `tests/smoke/ui_walkthrough.py` |
| Repaint probe | Windows that repaint (flicker) while idle | `tests/smoke/repaint_probe.py` |
| Code checker | A language whose errors would slip through | `tests/smoke/language_checks.py` |
| Release checks | A broken build or update reaching users | `scripts/quality/verify_release.py` |

`scripts/quality/run_all.py` runs every level and writes a report per version in
[docs/test-reports/](test-reports/), with screenshots of that version's real interface. Latest:
[1.0.7](test-reports/1.0.7.md).

## Automatic tests

259 Python tests and 7 Node suites, none of which need a model, a GPU or the internet (see
[tests/README.md](../tests/README.md)). Besides the core features, dedicated suites cover the areas of the
security and interface reviews:

- `test_security_audit.py` — DNS-rebinding protection, approvals, private engine keys, loop messages.
- `test_engine_loading.py` — an engine counts a model as loaded only when it really is; clear load
  errors; measured speeds; settings carried across engines.
- `test_engine_versions.py` — engine updates keep two versions, reuse unchanged parts, leave no archives.
- `test_checkers.py` — error detection that matches the sandboxed preview, and per-language checks.
- `test_interface_audit.py` — interface layout, translations and state kept in step with the core.

## Static analysis

| Tool | Scope | Rules |
|---|---|---|
| [ruff](https://docs.astral.sh/ruff/) | All Python | Undefined or shadowed names, unused results, bugbear and pylint error classes |
| [bandit](https://bandit.readthedocs.io/) | All Python | Medium and high severity security patterns (each finding reviewed by hand) |
| [ESLint](https://eslint.org/) | The assembled interface (`agent/ui/dist`) | `no-undef`, unreachable code, impossible comparisons, unsafe negation… |

`scripts/quality/static_analysis.py` runs all three with these rules. ESLint is first given a file
with deliberate errors, to prove the rules fire before trusting a clean result. Each bandit finding
is listed with the reason it is safe in `scripts/quality/bandit-reviewed.json`; a new one fails the
run until it is reviewed. Every text file is also scanned for stray control characters.

## Runs with real models

A core is started from source with a throw-away data folder on port 19381, so nothing touches a
real installation, and models are driven through the same API the interface uses:

`tests/smoke/real_models.py` runs on **llama.cpp**, **Strata** and **Strata Rust** with real GGUF
models (Mixture-of-Experts models of up to 35B parameters on Strata and Strata Rust), on a laptop
GPU with 6 GB of VRAM:

- Requests are written like a user would (in Spanish, without naming tools): write a Python file,
  build a web page that remembers its theme, edit a file.
- Checked: the files really exist and work (the Python compiles, the page opens without errors in
  the sandboxed preview); a denied approval leaves the file untouched; leaving a reply half way stops
  the engine within a second and the next request works; two chats at once never write into each
  other's folder; malformed requests get a clear 4xx; the engine's private server refuses requests
  without its key; an engine that cannot run a model says so at once; unloading closes the engine.
- A check the model gave no chance to make (it answered without trying to write, say) is reported
  as skipped, never as passed.
- Engine management is tested with real downloads from the official GitHub releases (llama.cpp CPU
  and Strata): versions kept, archives removed, unchanged parts reused.

## Interface

- **Walk-through** (`tests/smoke/ui_walkthrough.py`): opens every window and settings page in a
  headless browser at device scale 1, at the smallest allowed window (800×600) and at 1280×800, in
  dark and light themes and in more than one language, saving a full screenshot of each. Steps report
  what the screen shows so it can be compared with the core.
- **State consistency** (`tests/smoke/ui_consistency.py`): through clicks only, it loads a model,
  changes the context, sends a request and approves its write, stops a reply, unloads, switches
  engine, changes language and deletes a chat; after each action the screen is compared with the
  core's own API and the files on disk, and the page is reloaded to see what survives.
- **Hidden messages**: during that run an observer records any status, warning or error text written
  into a hidden element while its window is open, so messages always appear where the user looks.
- **Repaint probe** (`tests/smoke/repaint_probe.py`): counts visible repaints while windows sit
  idle, so a window that flickers is caught before a release.
- **Untrusted content** (`tests/smoke/xss_model_card.py`): the real Models window is fed a model
  card with 28 known XSS vectors (mutation XSS, `javascript:` and entity-encoded URLs, `srcset`,
  `srcdoc`, SVG/MathML namespaces, event handlers…); none may run, no dangerous element or attribute
  may survive, and the rest of the card must still render. Chat Markdown escapes all HTML first.

## Remote APIs

`tests/smoke/api_edge_cases.py` runs the API path against a local fake provider in the OpenAI and
Anthropic formats, without any account or key: reasoning plus tool calls, a provider that sends no
usage, 401/429/500 errors (readable, never showing the key or a provider's HTML), a stream cut half way
(reported, not shown as a complete answer), leaving a reply (the provider connection closes), switching
between provider models, and models declaring 1,048,576 tokens of context.

## Code checker

`tests/smoke/language_checks.py` gives the checker the agent uses after writing code a correct and a
broken file in every language it handles: Python (compiled, not just parsed), JSON, TOML, XML, SVG,
CSS, PowerShell, JavaScript (script, module, CommonJS; with Node.js and with the bundled browser) and
HTML. Languages that need a compiler (C, C++, Rust, Go, TypeScript, PHP, Ruby, Lua, shell, Java) must
be reported when the compiler is installed and "not checked" — never "fine" — when it is not. A page
that touches `localStorage` at load must be reported, because it fails in the sandboxed preview.

## Release checks

Before publishing, the packaged core is started from the build and checked (version, interface,
Host protection), and the installer is confirmed to contain no engines, no model profiles and no
personal data. After publishing, `scripts/quality/verify_release.py` downloads the signed manifest
from GitHub and validates it exactly as the previous version will, checks the installer's size and
SHA-256, fetches, verifies and applies the minor updates through the real components channel, and
confirms that a manifest changed by one byte or signed for something else is refused.

## Security review

Each release is reviewed by hand, in addition to the tools above, in these areas:

- **Local server** — only loopback host names are served (DNS-rebinding protection), cross-site
  requests are refused, and the engines' own servers require a private key per session.
- **Files** — the access policy rejects absolute paths, `..`, drive letters, alternate data streams,
  links and junctions; replacements are staged and swapped atomically; earlier versions are kept.
- **Commands** — isolated execution in a Windows process container without network; whole-PC access
  is an explicit choice.
- **Approvals** — enforced in the core for every tool call, MCP servers included; writes, restores,
  commands and network access ask first in "Ask" mode.
- **Untrusted content** — model cards, release notes and chat output are sanitised; chat templates
  render in a sandboxed Jinja environment; the desktop window's browser tabs have no app permissions.
- **Updates** — Ed25519 signatures, version and checksum checks for V-Agent and its minor updates;
  official release URLs and published digests for engines and model downloads.

Fixes are listed per version in the [changelog](../CHANGELOG.md).

## Not covered yet

- The installer has no Authenticode signature, so Windows SmartScreen warns on first install
  (updates are still verified with the maintainer's Ed25519 key).
- Real-model runs use one Windows 11 laptop with an NVIDIA GPU; AMD/Intel (Vulkan) and CPU-only
  machines are covered by the automatic tests but not by model runs.
- The inference engines themselves (llama.cpp, Strata, Strata Rust) are upstream projects and are
  not fuzzed here.
- Third-party MCP servers run with the permissions you give them; V-Agent checks approvals, not
  their code.

Found something? Report security issues privately ([SECURITY.md](../SECURITY.md)) and anything else
in [Issues](https://github.com/IsValorum/V-Agent/issues).
