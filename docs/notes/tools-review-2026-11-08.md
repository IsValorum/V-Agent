# Tools review — 2026-11-08

Reviewed installed Unsloth Studio: backend/state/tool_policy.py and core/inference/tools.py in its local uv package. Its ask/auto/off/full permission policies are separate from OS isolation. VAL adapts the behavior using its own host-side approval broker, without copying model-facing instructions or claiming OS process isolation.

Primary references:
- https://opencode.ai/docs/tools/
- https://unsloth.ai/blog/security
- https://github.com/aaif-goose/goose/issues/6193

VAL already has confined per-chat/project file access, numbered/paged reads, exact atomic text edits, file history, draft recovery, project symbols, syntax/project checks, headless HTML diagnostics, bounded shell output, web search/reading and HF CLI/SDK access. These cover normal code editing well. Permissions add no tool descriptions or prompt tokens.

Important gaps compared with broader coding harnesses: dedicated content/file search, persistent interactive terminal sessions, LSP semantic navigation, interactive browser automation and native desktop accessibility/mouse/keyboard tools. web_render diagnoses a document; it does not navigate arbitrary applications. shell_run executes commands; it is not a persistent terminal. Folder confinement does not isolate arbitrary host processes, so commands remain blocked in folder mode. HF and unknown mutating actions ask in confirm-changes mode.

Recommended order: bounded project search (short schema, paged results); persistent managed command sessions; optional language-server diagnostics; then optional browser/desktop tools advertised only when activated. Avoid installing a large always-visible desktop tool catalog. Keep raw outputs available locally and return focused excerpts with continuation references.

Thinking controls are inferred from external Jinja variables and explicit reasoning_effort branches in the active external template or embedded GGUF. Identically handled levels may be aliases; xHigh is not guaranteed to improve a model. Unknown/fixed templates receive no invented thinking switches. API reasoning requires future provider capability metadata and currently stays provider-controlled.
