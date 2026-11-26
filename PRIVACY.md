# Privacy

V-Agent has **no telemetry, no analytics and no account**. Your chats, settings and files stay on your
computer, in `%LOCALAPPDATA%\V-Agent-Data` and in the folders you choose.

V-Agent connects to the internet only for things you start or enable:

| Connection | When |
|---|---|
| GitHub releases (this repository) | checking for and downloading signed V-Agent updates |
| GitHub releases of llama.cpp, Strata, Strata Rust | checking and installing engines |
| The API you configure (OpenAI- or Claude-compatible) | when you chat with an API model; your key is stored encrypted with Windows DPAPI |
| Web search / page reading / HTTP / browser tools | only when those tools are enabled and the agent uses them |
| Hugging Face | only when you use the Hugging Face tools |
| MCP servers and plugins you install | according to each server |

Local models run entirely on your PC.

What V-Agent keeps on disk, and for how long:

| Data | Where | Kept |
|---|---|---|
| Saved chats | `sessions.sqlite3` | until you delete the chat |
| Temporary chats | only their working folder (never the history) | removed when you leave the chat |
| Per-reply run records (for recovering an interrupted reply) | `runs\` | removed a day after the reply is saved in its chat |
| Earlier versions of files the agent changed | `versions\` | the last 100 per file (files over 32 MB are not copied) |
| Each chat's working folder | `workspaces\conversations\` | until you delete the chat |
