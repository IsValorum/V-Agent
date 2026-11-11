# Local agent client

The browser is a client of the local API. Model execution, project selection,
conversation storage and tool execution remain in Python services so another
desktop client can use the same API.

## Project scope

`GET /api/projects?conversation_id=...` returns registered folders and this
conversation's selection. `POST /api/projects/select` selects a registered
`project_id`, registers a `path`, or clears the selection with `project_id: null`.
The modifying request must originate from the local UI and cannot run during
generation. Selections persist in `projects.json`; chat content stays in the
existing local database. Selecting a project does not enable arbitrary commands.

The signed conversation ticket resolves the same project in the agent, PC MCP,
HF transfers, draft recovery and file history. Without a project, each conversation
retains its independent workspace. Relative paths cannot escape the selected root.

## Diagnostics

`code_check` checks supported file syntax or lists a project's available checks.
For a directory, detection covers Node scripts/TypeScript, Python, Cargo, Go,
.NET and Maven. It never downloads missing tools or silently runs scripts.
To execute a listed check, use its `check` ID and `run: true`, with full-PC command
access explicitly enabled. Results include exit code, stdout, stderr, duration,
timeout and truncation. Commands are bounded and never automatically retried.

Other languages and build systems can define `.strata/checks.json`:

```json
{"checks":[{"id":"check","command":["your-compiler","--check","source.ext"]}]}
```

Commands are argument arrays, not shell strings. Custom checks also require
full-PC access. Project commands can execute project code; a selected folder alone
is not permission to run them. A syntax pass is not a correctness guarantee.

`web_render` separately checks HTML runtime errors. Optional scene inspection
provides bounded Three.js telemetry and moving-box intersection warnings; it is
one specialist adapter, not a universal visual or semantic judge. Fast automatic
write/edit checks do not invoke advanced scene inspection.

## Optional vision

Vision controls belong to the selected model. Supply that model's compatible
mmproj GGUF and an installed `strata-vision` executable. Configuration is saved
locally and takes effect on the next manual model load. CPU encoding is elastic
and starts only when an image is used. Missing components are reported instead of
pretending vision is available. Selecting a file never loads a model. Enabling
vision requires a verified architecture, but compatibility still needs a real
image test with the matching projector/encoder; a filename is not proof.

No account tokens, model weights or machine-specific configuration should be
published with the source. Packaging and public release require a separate
portability and dependency review.

## Menu rendering

Ambient gradients, grain and glass background blur are baked into bounded PNG
bitmaps on theme/viewport changes, not maintained as live CSS filters or SVG blend
layers. Glass shows the blurred ambient image, not a live blur of transcript text.
Menus use ordinary centered layout without a transform or resize-observer feedback
loop. Help opens explicitly; pointer movement does not create top-layer popovers.
The scheduler regression is `node tests/prueba_fondo_estatico.cjs`.
