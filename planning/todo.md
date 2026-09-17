- [x] **Stage 1:** Initial setup (git, podman, planning artifacts). 
- [x] **Stage 2:** Python environment setup and FastMCP server skeleton. *(complete)*
- [x] **Stage 3:** Implement CLI wrapper tools (`list_containers`, `get_container_logs`).
- [x] **Stage 4:** Implement `diagnose_container_logs` with LLM integration.
- [x] **Stage 5:** Test with an MCP client (e.g., Claude Desktop or test script). *(completed — CLI & demo verified)*
- [x] **Stage 6:** Final Polish (README, export agent logs, prepare demo). *(completed)*

- [x] **Package CLI:** `server.py` and `pyproject.toml` updated to package the FastMCP server as a CLI tool and add an entry point (`podman-diagnostics`).
- [x] **Argparse options:** CLI options `--container <id>`, `--mcp` (run server stdio mode), and `--demo` added.
- [x] **Error handling & UX:** Added explicit handling when a container isn't found and clear status/error messages; added offline diagnostics fallback when LLM is unavailable.
