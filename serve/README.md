# serve/ — request layer and MCP hub (vendored)

This package comes from [PolyStrata](https://github.com/simplexai-labs/PolyStrata) and keeps its MIT
license ([LICENSE.Strata](../LICENSE.Strata)).

V-Agent uses three parts of it directly:

| File | Used for |
|---|---|
| `mcp.py` | The MCP hub: starts the tool servers, lists their tools and routes calls (stdio and HTTP). |
| `frontend.py` | Chat-template rendering and tool-call parsing shared with the engine. |
| `models.py` | Discovering locally configured models. |

The rest is the OpenAI/Anthropic-compatible engine server that runs when the core is started with
`--role strata-server` (Strata engine only).

The upstream test suite (about 960 tests) is not included here: it needs PolyStrata's own web
interface and GPU engine. V-Agent's tests for the parts it relies on are in [`tests/`](../tests/).
