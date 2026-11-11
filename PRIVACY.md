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
