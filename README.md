# podman-diagnostics

A FastMCP server and CLI tool designed to fetch local Podman container logs and produce LLM-based root-cause diagnostics within seconds. 

## Features
- **FastMCP Integration:** Exposes `list_containers` and `get_container_logs` tools for MCP clients (like Claude Desktop or VS Code).
- **AI Diagnostics:** `diagnose_container_logs` uses Gemini (via `google-genai`) to extract stack traces, error codes, and next steps.
- **Dual Interface:** Run as an MCP server via stdio, or as a standalone CLI tool.
- **Offline Demo Mode:** Includes a `--demo` flag that works entirely offline with mock data for instant verification.

## Quick Start

```bash
# 1. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 2. Install the CLI
pip install -e .

# 3. Verify it works instantly (No API keys or containers required)
podman-diagnostics --demo

# 4. Run the FastMCP server for VS Code MCP integration (stdio)
podman-diagnostics --mcp

# 5. Diagnose a live container by name or id
podman-diagnostics --container test-crash
```

## Environment Config
To enable live LLM diagnostics, set `GEMINI_API_KEY` in your environment or in a `.env` file in the project root:

```text
GEMINI_API_KEY=your_key_here
# Optional: Override the default model
GEMINI_MODEL=gemini-3.6-flash
```

## Trade-offs & Simplifications
To keep this project focused and completable within the 2-hour window, I made the following architectural choices:
* **Native CLI over Containerization:** I chose to package this as an installable Python CLI rather than a container. Running this tool *inside* a container would require the user to mount their host's Podman socket (`-v /run/user/1000/podman/podman.sock:/run/podman.sock`), which adds significant friction to the testing experience.
* **Graceful Degradation:** If the Gemini API fails or is unconfigured, the tool gracefully returns a sanitized raw log output rather than forcing a heavy local LLM dependency (like Ollama). 

## AI Tooling & Handoff
This project was built using an AI coding agent. All architectural decisions, task breakdowns, and agent handoff artifacts are preserved in the `planning/` directory.

## Example test container

```bash
# Start a small test container that emits logs then raises an error
podman pull python:3.11-alpine
podman run -d --name test-crash python:3.11-alpine sh -c "echo 'App starting...'; sleep 1; python -c 'raise ConnectionRefusedError(\"could not connect\")'"

# View logs (works for running or stopped containers)
podman logs --tail 200 test-crash

# Use the CLI to run diagnostics (uses LLM if configured; otherwise offline fallback)
python3 server.py --container test-crash
# or, after installing the package:
podman-diagnostics --container test-crash

# Clean up
podman rm -f test-crash
```

Notes:
- `podman ps` shows only running containers; use `podman ps -a` to list stopped ones.
- If LLM diagnostics are desired, ensure `GEMINI_API_KEY` is exported or in `.env`.
- Use `--demo` to run an offline example without Podman: `podman-diagnostics --demo`.
