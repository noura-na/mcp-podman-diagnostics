# FastMCP Podman Diagnostics Developer Tool — Architectural Outline

Core concept
- Expose local container logs and LLM-based diagnostics to MCP clients via a FastMCP Python server. The server wraps the Podman CLI to fetch logs and uses an LLM client to extract stack traces, error codes, and root-cause summaries.

Tech stack
- Python 3.10+
- `fastmcp` for MCP server and tool exposure
- `subprocess` to call `podman` (no direct Podman Python SDK required)
- An LLM client library (e.g., OpenAI, Anthropic, or a local LLM SDK)

High-level components
- FastMCP server: registers tools and routes MCP requests to local handlers.
- CLI wrapper module: small, testable functions that call `podman` via `subprocess` and return structured results.
- LLM adapter: prepares prompts, calls the LLM, and post-processes responses.
- Sanitizer: removes secrets, long binary blobs, and sensitive metadata from logs before returning or sending to the LLM.
- Auth & Safety layer: enforces policies, rate-limits, and environment restrictions.

Tools / APIs exposed to MCP clients
- `list_containers()`
  - Implementation: run `podman ps --format json` and parse JSON output.
  - Output: list of running containers with `id`, `image`, `names`, `status`, and `ports`.
  - Errors: surface structured error messages if Podman is not available or output is invalid.

- `get_container_logs(container_id: str, tail: int = 500)`
  - Implementation: run `podman logs --tail {tail} {container_id}`.
  - Sanitization: remove or redact env-like patterns (API keys, tokens), strip control characters, and truncate extremely long lines.
  - Output: sanitized log text plus metadata (truncated=true/false, original_line_count).

- `diagnose_container_logs(container_id: str, tail: int = 200)`
  - Flow: fetch logs via `get_container_logs`, assemble a prompt that asks the LLM to extract stack traces, error codes, timelines, and a concise root-cause summary.
  - LLM prompt guidance: include short examples, ask for JSON-structured output (fields: `stack_traces`, `error_codes`, `summary`, `confidence`, `actionable_next_steps`).
  - Post-process: validate returned JSON, normalize stack traces, and attach confidence metadata.

Data flow
1. MCP client calls `diagnose_container_logs` with a container id.
2. FastMCP handler calls `get_container_logs`.
3. Sanitizer cleans the logs; if logs are large, store a truncated copy and include a pointer to full logs on disk (if permitted).
4. LLM adapter sends sanitized logs + structured prompt to LLM and receives a JSON response.
5. Handler returns structured diagnostics to the MCP client.

Security & privacy
- Sanitize logs before any network transmission.
- Avoid sending secrets to third-party LLMs unless explicitly permitted; support enterprise LLM endpoints or local models.
- Run server with least privileges; avoid running as root.
- Require explicit environment variables or a config file for enabling remote LLM calls and storing API keys.

Operational concerns
- Podman availability: detect and fail fast if `podman` not on PATH.
- Concurrency: FastMCP can dispatch short-running subprocess calls concurrently; implement limits (max parallel `podman` calls).
- Observability: emit server-level logs, metrics for LLM calls, and rate-limit events.

Testing and verification
- Unit tests for CLI wrappers (mock `subprocess` outputs).
- Integration test that runs against a local Podman test container.
- End-to-end check using a simple MCP client script to exercise `diagnose_container_logs`.

Developer notes
- Keep CLI wrapper functions small and pure where possible to ease mocking.
- Prefer JSON-structured LLM replies and validate them strictly before exposing to clients.
- Provide a `--dry-run` or `--no-llm` mode to allow offline testing without LLM calls.

Trade-offs & Scope Limitations (2-Hour Window)

To ensure delivery within the time constraint, the following architectural compromises were made:

- Native CLI over Containerized Server: I packaged the tool as a native Python CLI rather than a Podman container. Running this server inside a container would require complex Podman socket-mounting (`-v /run/user/1000/podman/podman.sock:/run/podman.sock`), which degrades the zero-friction testing experience.

- Dual Interface: Instead of building a dedicated frontend, we used `argparse` to create a standalone CLI alongside the FastMCP `stdio` transport. This allows users to test diagnostics immediately via `--container` without needing a configured MCP client.

- Dropped Complexities: Advanced features listed above—such as the Auth & Safety layer, parallel concurrency limits, and a full unit testing suite—were scoped out in favor of a robust `--demo` mode for instant local validation.