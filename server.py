#!/usr/bin/env python3
import argparse
import json
import re
import subprocess
from typing import Any, Dict
import os
from typing import List, Optional
import requests
import sys

from fastmcp import FastMCP
from dotenv import load_dotenv

load_dotenv()  # Load environment variables from .env file
# Create the FastMCP server instance
server = FastMCP(name="podman-diagnostics")


@server.tool("list_containers")
def list_containers() -> Any:
    """Return running Podman containers as parsed JSON.

    Runs: `podman ps --format json` and returns the decoded JSON list.
    On error returns a dict with `error` and `details`.
    """
    try:
        proc = subprocess.run(
            ["podman", "ps", "--format", "json"],
            capture_output=True,
            text=True,
            check=True,
        )
        out = proc.stdout.strip()
        if not out:
            return []
        return json.loads(out)

    except subprocess.CalledProcessError as exc:
        return {
            "error": "podman command failed",
            "returncode": exc.returncode,
            "stderr": exc.stderr.strip() if exc.stderr else None,
        }
    except json.JSONDecodeError:
        return {"error": "failed to parse podman output as JSON", "raw": out}


def _sanitize_logs(text: str, max_line_length: int = 1000) -> Dict[str, Any]:
    """Sanitize logs by redacting likely secrets, stripping control chars, and truncating long lines.

    Returns a dict: {"text": sanitized_text, "truncated": bool, "original_line_count": int}
    """
    # redact env-like key patterns: API_KEY=..., token=..., password=...
    redacted = re.sub(r"(?i)(?:api[_-]?key|token|secret|password)[\s]*[:=][\s]*\S+", "<REDACTED>", text)

    # redact bearer tokens in headers
    redacted = re.sub(r"(?i)bearer\s+[A-Za-z0-9\-\._~\+\/]+=*", "<REDACTED>", redacted)

    # remove control characters except newline and tab
    redacted = re.sub(r"[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f]+", "", redacted)

    lines = redacted.splitlines()
    truncated_flag = False
    out_lines = []
    for ln in lines:
        if len(ln) > max_line_length:
            out_lines.append(ln[:max_line_length] + "...<TRUNCATED_LINE>")
            truncated_flag = True
        else:
            out_lines.append(ln)

    sanitized = "\n".join(out_lines)
    return {"text": sanitized, "truncated": truncated_flag, "original_line_count": len(lines)}


def _discover_compatible_model(api_key: str) -> Optional[str]:
    """List available models via installed clients and pick a likely text-generation model."""
    try:
        from google import genai
        # Explicitly pass the API key
        client = genai.Client(api_key=api_key)
        models = client.models.list()
        
        candidates = [m.name for m in models if m.name]
        
        for name in candidates:
            ln = name.lower()
            # Prioritize Gemini flash/pro models
            if "gemini" in ln and "vision" not in ln:
                return name
        return candidates[0] if candidates else None
    except Exception as e:
        print(f"[debug] google.genai discovery failed: {e}", file=sys.stderr)
        return "gemini-3.6-flash"

def _container_exists(container_id: str) -> bool:
    """Return True if `podman inspect <container_id>` succeeds."""
    if not container_id:
        return False
    try:
        proc = subprocess.run(["podman", "inspect", container_id], capture_output=True, text=True)
        return proc.returncode == 0
    except Exception:
        return False


def _offline_diagnostics(log_text: str) -> Dict[str, Any]:
    """Lightweight regex-based diagnostics when LLM is unavailable.

    Attempts to extract stack traces, exception names, and error lines
    and returns a best-effort summary and suggested next steps.
    """
    traces: List[str] = []
    errors: List[str] = []

    # Capture Python tracebacks blocks
    tb_blocks = re.findall(r"Traceback\b[\s\S]+?(?=\n\w|$)", log_text)
    for tb in tb_blocks:
        traces.append(tb.strip())

    # Capture Exception/Error names (e.g., ConnectionRefusedError)
    exc_names = re.findall(r"([A-Za-z_][A-Za-z0-9_]+Error)\b", log_text)
    for name in exc_names:
        if name not in errors:
            errors.append(name)

    # Capture ERROR log lines
    err_lines = [ln.strip() for ln in log_text.splitlines() if re.search(r"\bERROR\b|\bError\b", ln, re.I)]
    for ln in err_lines:
        if ln not in traces and ln not in errors:
            traces.append(ln)

    summary = "No LLM available. Lightweight diagnostics extracted from logs."
    if errors:
        summary = f"Detected exceptions: {', '.join(errors)}."
    elif traces:
        summary = f"Found {len(traces)} trace lines / blocks."

    actionable = []
    if "ConnectionRefusedError" in errors or re.search(r"connection refused", log_text, re.I):
        actionable.append("Verify the target service is running and reachable from the container network")
        actionable.append("Check connection strings and firewall rules")
    if "TimeoutError" in errors or re.search(r"timed out", log_text, re.I):
        actionable.append("Check service responsiveness and increase timeouts if appropriate")

    return {
        "stack_traces": traces,
        "error_codes": errors,
        "summary": summary,
        "confidence": 0.5,
        "actionable_next_steps": actionable or ["Inspect the full logs for more context"],
    }


@server.tool("get_container_logs")
def get_container_logs(container_id: str, tail: int = 500) -> Dict[str, Any]:
    """Fetch and sanitize logs for `container_id` using `podman logs --tail N`.

    Returns dict with `logs` (sanitized), `truncated`, and `original_line_count`, or an `error` key.
    """
    if not container_id:
        return {"error": "container_id is required"}

    cmd = ["podman", "logs", "--tail", str(int(tail)), container_id]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
        raw = (proc.stdout or "").strip() + "\n" + (proc.stderr or "").strip()
        
        sanitized = _sanitize_logs(raw)
        return {
            "container_id": container_id,
            "logs": sanitized["text"],
            "truncated": sanitized["truncated"],
            "original_line_count": sanitized["original_line_count"],
        }
    except subprocess.CalledProcessError as exc:
        # If the container does not exist, return a clear error for CLI consumers
        stderr = exc.stderr.strip() if exc.stderr else None
        if stderr and ("no such" in stderr.lower() or "not found" in stderr.lower()):
            return {"error": "container_not_found", "details": stderr}
        return {"error": "podman logs failed", "returncode": exc.returncode, "stderr": stderr}
    except Exception as exc:
        return {"error": "unexpected error", "details": str(exc)}


@server.tool("diagnose_container_logs")
def diagnose_container_logs(container_id: str, tail: int = 200) -> Dict[str, Any]:
    """Fetch container logs, send to an LLM (if configured), and return structured diagnostics.

    The LLM integration is optional: if the `` package is installed and
    `GEMINI_API_KEY` is set, it will be used. Otherwise the tool returns the
    sanitized logs and a note that the LLM is unavailable.
    """
    # Fetch logs
    logs_res = get_container_logs(container_id, tail=tail)
    if logs_res.get("error"):
        return {"error": "failed_to_fetch_logs", "details": logs_res}

    sanitized = logs_res.get("logs", "")

    prompt = (
        "You are an automated diagnostics assistant. Given the following container logs,\n"
        "extract any stack traces, list distinct error codes or exception names, and provide a concise root-cause summary.\n"
        "Return a JSON object with keys: stack_traces (list of strings), error_codes (list), summary (string), confidence (0-1 float), actionable_next_steps (list of strings).\n\n"
        "Logs:\n" + sanitized
    )

    api_key = os.getenv("GEMINI_API_KEY")
    model = os.getenv("GEMINI_MODEL")

    # If no API key is present, return an offline diagnostics fallback
    if not api_key:
        offline = _offline_diagnostics(sanitized)
        return {
            "container_id": container_id,
            "logs": sanitized,
            "llm": "unavailable",
            "details": "GEMINI_API_KEY not set",
            "diagnostics_offline": offline,
        }

    if not model:
        model = _discover_compatible_model(api_key)

    text = None
    
    # 1. Try the new `google-genai` SDK
    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model,
            contents=prompt,
        )
        text = response.text

        # Try to parse JSON out of the successful LLM response
        if not text:
            return {"container_id": container_id, "error": "LLM returned empty text"}
            
        try:
            # Strip markdown formatting in case the LLM wrapped the JSON in a code block
            clean_text = text.strip()
            if clean_text.startswith("```json"):
                clean_text = clean_text[7:-3].strip()
            elif clean_text.startswith("```"):
                clean_text = clean_text[3:-3].strip()
                
            parsed = json.loads(clean_text)
            return {"container_id": container_id, "diagnostics": parsed}
        except json.JSONDecodeError:
            # Fallback if the LLM didn't return valid JSON
            return {"container_id": container_id, "diagnostics_raw": text}

    except Exception as exc:
        offline = _offline_diagnostics(sanitized)
        return {
            "container_id": container_id,
            "logs": sanitized,
            "llm": "unavailable",
            "details": f"SDK failed: {str(exc)}",
            "diagnostics_offline": offline,
        }

def _demo_run() -> int:
    """Run an offline demo using fake logs and a fake LLM response."""
    print("[demo] Running offline demo...")
    fake_logs = (
        "2026-09-17T12:00:00Z ERROR ConnectionRefusedError: Could not connect to 10.0.0.5:5432\n"
        "Traceback (most recent call last):\n"
        "  File \"/app/main.py\", line 12, in <module>\n"
        "ConnectionRefusedError: [Errno 111] Connection refused\n"
    )
    sanitized = _sanitize_logs(fake_logs)
    print("[demo] Sanitized logs:\n")
    print(sanitized["text"]) if sanitized else print("[demo] <no logs>")

    fake_llm = {
        "stack_traces": ["ConnectionRefusedError at /app/main.py:12"],
        "error_codes": [],
        "summary": "The application failed to connect to a database at 10.0.0.5:5432; connection refused.",
        "confidence": 0.9,
        "actionable_next_steps": [
            "Verify database is running and reachable from container network",
            "Check connection string and firewall settings",
        ],
    }
    print('\n[demo] Fake LLM diagnostics:')
    print(json.dumps(fake_llm, indent=2))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    """Command-line entrypoint.

    Options:
    - --container <id> : fetch logs and run diagnostics for the container
    - --mcp            : run the FastMCP server in stdio mode (for VS Code MCP)
    - --demo           : run an offline demo with fake logs/LLM
    """
    parser = argparse.ArgumentParser(prog="podman-diagnostics")
    parser.add_argument("--container", "-c", help="Container id or name to diagnose", required=False)
    parser.add_argument("--mcp", action="store_true", help="Run the FastMCP server (stdio transport)")
    parser.add_argument("--demo", action="store_true", help="Run offline demo with fake logs and LLM response")
    args = parser.parse_args(argv)

    if args.demo:
        return _demo_run()

    if args.mcp:
        print("[mcp] Starting FastMCP server (stdio transport). Press Ctrl-C to exit.")
        try:
            server.run(transport="stdio")
            return 0
        except KeyboardInterrupt:
            print("[mcp] Interrupted by user.")
            return 0
        except Exception as exc:
            print(f"[mcp] Failed to start server: {exc}")
            return 2

    if args.container:
        cid = args.container
        print(f"[cli] Diagnosing container: {cid}")
        if not _container_exists(cid):
            print(f"[error] Container '{cid}' not found. Use 'podman ps -a' to list containers.")
            return 3
        print("[cli] Fetching logs...")
        logs_res = get_container_logs(cid, tail=1000)
        if logs_res.get("error"):
            print(f"[error] Failed to fetch logs: {logs_res}")
            return 4
        print("[cli] Running diagnostics (LLM if configured)...")
        diag = diagnose_container_logs(cid, tail=1000)
        print(json.dumps(diag, indent=2))
        return 0

    # If no args provided, print help
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
