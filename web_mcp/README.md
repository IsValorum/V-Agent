# web_mcp/ — web tools

MCP servers that give the model access to the web. Each one runs as its own process
(`strata-core.exe --role web` / `--role webtools`).

| File | Tools |
|---|---|
| `buscador_mcp.py` | `web_search` and `web_visit`: DuckDuckGo text search and readable page text. |
| `busqueda_local.py` | Search policy shared by the above (region, safe search, result shaping). |
| `http_tools_mcp.py` | HTTP requests, API calls and downloads for the Standard and Full agent modes, saved inside the chat's folder. |

Defaults such as the search region are user settings (`agent/mcp_options.py`), never part of the
model prompt.
