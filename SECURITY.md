# Security policy

## Reporting a vulnerability

Please report security problems **privately** through GitHub's
[private vulnerability reporting](../../security/advisories/new) for this repository. Do not open a
public issue for anything that could put users at risk.

Include the V-Agent version (Settings → General), what an attacker could achieve, and the steps to
reproduce. You will receive an acknowledgement, and a fix is released as a signed update.

## Supported versions

Only the latest release receives security fixes. V-Agent checks for signed updates from this
repository; update when it offers a new version.

## Security model in brief

- **Updates** are accepted only when their manifest carries a valid Ed25519 signature from the
  maintainer's private key (never stored in this repository), the version is newer, and the
  installer's size and SHA-256 match the signed manifest.
- **Components** (minor updates to MCP servers and tools) use the same signature, are tied to the
  installed version and a fixed file list, and are re-verified at every start; on any mismatch the
  bundled code is used.
- **Engines** are downloaded only from their official GitHub release URLs and checked against the
  digest GitHub publishes, then tested before activation; the previous version can be restored.
- **Isolated access** runs commands in a Windows process container with no network and write access
  limited to the chat or project folder. **Full PC** access is an explicit choice.
- **Approvals**: tools that change files, restore earlier versions, run commands or use the network
  ask first (depending on the selected mode). Approvals are enforced by the core for every tool,
  MCP servers included. Denied actions stop the turn and their content is not kept.
- **Local servers**: the local API listens on 127.0.0.1 only, answers only to loopback host names
  (protection against DNS rebinding) and checks the request origin. The engine servers it starts
  (llama.cpp, Strata Rust) require a private key generated for each session.
- **Untrusted content**: model cards and release notes are sanitised before display, chat output is
  escaped, chat templates render in a sandboxed environment, and pages are checked under the same
  isolation as the preview.

How each part is tested and reviewed: [docs/QUALITY.md](docs/QUALITY.md).
