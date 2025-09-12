#!/usr/bin/env python3
import asyncio
import json
import os
import re
import shutil
from pathlib import Path
from typing import Optional, Dict, Any, List

from mcp.server.fastmcp import FastMCP

AGENTD_DIR = Path(os.environ.get("AGENTD_DIR", os.path.expanduser("~/.agentd")))
LOG_DIR = AGENTD_DIR / "logs"
SESSION = os.environ.get("AGENTD_SESSION", "agentd")
CLI_WINDOW = os.environ.get("AGENTD_CLI_WINDOW", "cli")

app = FastMCP(
    name="agentd",
    instructions="Expose tmux-based async jobs and logs via MCP.",
)


def _read_text(path: Path, fallback: str = "") -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return fallback


def _job_rc_path(token: str) -> Path:
    return AGENTD_DIR / f"{token}.rc"


def _job_log_path(token: str) -> Path:
    return LOG_DIR / f"{token}.log"


def _shell_quote(s: str) -> str:
    return shutil.quote(s)


def _list_job_tokens() -> List[str]:
    if not AGENTD_DIR.exists():
        return []
    toks = []
    for p in AGENTD_DIR.glob("*.rc"):
        toks.append(p.stem)
    # Include logs without rc as well
    if LOG_DIR.exists():
        for p in LOG_DIR.glob("*.log"):
            toks.append(p.stem)
    return sorted(set(toks))


def _job_status(token: str) -> Dict[str, Any]:
    rc_path = _job_rc_path(token)
    log_path = _job_log_path(token)
    rc_val: Optional[int] = None
    if rc_path.exists():
        try:
            rc_val = int(rc_path.read_text().strip())
        except Exception:
            rc_val = None
    status = {
        "token": token,
        "rc": rc_val,
        "has_log": log_path.exists(),
        "rc_path": str(rc_path),
        "log_path": str(log_path),
    }
    return status


def _bin(path: str) -> Path:
    return Path(__file__).resolve().parents[1] / "bin" / path


def _tmux_ok() -> bool:
    from shutil import which
    return which("tmux") is not None


def _target_file() -> Path:
    return AGENTD_DIR / "agent_pane"


def _read_target() -> Optional[str]:
    p = _target_file()
    if not p.exists():
        return None
    t = p.read_text().strip()
    return t or None


def _tmux_pane_exists(target: str) -> bool:
    import subprocess
    try:
        subprocess.run(["tmux", "list-panes", "-t", target], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def _detect_self_pane() -> Optional[str]:
    """If the server was launched from inside tmux, resolve its own pane as session:win.pane.

    Requires TMUX_PANE to be set (server launched inside tmux).
    """
    if not _tmux_ok():
        return None
    import subprocess
    pane_env = os.environ.get("TMUX_PANE")
    fmt = "#{session_name}:#{window_index}.#{pane_index}"
    try:
        if not pane_env:
            return None
        out = subprocess.run(["tmux", "display-message", "-p", "-t", pane_env, fmt], capture_output=True, text=True, check=True)
        target = out.stdout.strip()
        if target and _tmux_pane_exists(target):
            return target
    except Exception:
        return None
    return None


SELF_PANE = _detect_self_pane()


def _ensure_bootstrap(session: Optional[str] = None, window: Optional[str] = None, cmd: Optional[str] = None) -> Optional[str]:
    """Ensure a valid target pane is recorded. Returns target if available."""
    if not _tmux_ok():
        return None
    saved = _read_target()
    if saved and _tmux_pane_exists(saved):
        return saved
    boot = _bin("agentd-bootstrap")
    if not boot.exists():
        return saved
    args = [str(boot)]
    if session or SESSION:
        args += ["-s", session or SESSION]
    if window or CLI_WINDOW:
        args += ["-w", window or CLI_WINDOW]
    if cmd:
        args += ["-c", cmd]
    import subprocess
    env = os.environ.copy()
    env.setdefault("AGENTD_SESSION", session or SESSION)
    try:
        subprocess.run(args, check=True, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        return saved
    return _read_target()


def _self_session() -> Optional[str]:
    if not SELF_PANE:
        return None
    # format: session:win.pane -> session
    return SELF_PANE.split(":", 1)[0]


def _session_cli_pane(session: str) -> str:
    return f"{session}:{CLI_WINDOW}.0"


def _cli_pane_exists(session: str) -> bool:
    target = _session_cli_pane(session)
    return _tmux_pane_exists(target)


@app.tool()
def tmux_run(
    cmd: str,
    target_key: str | None = None,
    target: str | None = None,
    session: str | None = None,
    window: str | None = None,
    pane: int | None = None,
) -> dict:
    """Run a long job under tmux via job-run and return the token.

    Args:
        cmd: Shell command to execute under job-run.

    Returns:
        {"token": str}
    """
    # Use the local bin scripts
    repo_bin = Path(__file__).resolve().parents[1] / "bin"
    job_run = repo_bin / "job-run"
    if not job_run.exists():
        raise RuntimeError(f"job-run not found at {job_run}")

    env = os.environ.copy()
    env.setdefault("AGENTD_SESSION", SESSION)
    import subprocess
    args = [str(job_run), cmd]
    # Self-only default for MCP: always send back to the server's own pane if available
    if not SELF_PANE:
        raise RuntimeError("Self-only: MCP server must run inside tmux")
    env["JOB_TARGET_PANE"] = SELF_PANE
    # Execute job-run and capture token
    res = subprocess.run(
        args,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    token = res.stdout.strip().splitlines()[-1].strip()
    return {"token": token}


@app.tool()
def tmux_bootstrap(session: Optional[str] = None, window: Optional[str] = None, cmd: Optional[str] = None, key: Optional[str] = None) -> dict:
    t = _ensure_bootstrap(session=session, window=window, cmd=cmd)
    if key and t:
        p = _bin("agentd-target")
        if p.exists():
            import subprocess
            subprocess.run([str(p), "set", key, t], check=False)
    return {"target": t}


@app.tool()
def tmux_get_target(key: Optional[str] = None) -> dict:
    if key:
        p = AGENTD_DIR / "targets" / f"{key}.pane"
        return {"target": _read_text(p, fallback="")}
    return {"target": _read_target()}


@app.tool()
def tmux_set_target(target: str, key: Optional[str] = None) -> dict:
    if not target:
        raise ValueError("target required")
    if not _tmux_pane_exists(target):
        raise RuntimeError(f"tmux pane not found: {target}")
    if key:
        tf = AGENTD_DIR / "targets" / f"{key}.pane"
        tf.parent.mkdir(parents=True, exist_ok=True)
        tf.write_text(target)
    else:
        tf = _target_file()
        tf.parent.mkdir(parents=True, exist_ok=True)
        tf.write_text(target)
    return {"target": target}


@app.tool()
def tmux_list_targets() -> dict:
    out: Dict[str, str] = {}
    default = _read_target()
    if default:
        out["default"] = default
    tdir = AGENTD_DIR / "targets"
    if tdir.exists():
        for p in tdir.glob("*.pane"):
            out[p.stem] = _read_text(p, "")
    return out


@app.tool()
def tmux_status(token: Optional[str] = None) -> dict:
    """Get status for a token or all tokens if omitted."""
    if token:
        return _job_status(token)
    return {t: _job_status(t) for t in _list_job_tokens()}


@app.tool()
def tmux_logs(token: str, tail: Optional[int] = None) -> dict:
    """Get logs for a token. Optionally limit to last N lines."""
    log_path = _job_log_path(token)
    if not log_path.exists():
        return {"token": token, "log": "", "exists": False}
    text = _read_text(log_path)
    if tail is not None and tail > 0:
        lines = text.splitlines()
        text = "\n".join(lines[-tail:])
    return {"token": token, "exists": True, "log": text}


@app.tool()
def tmux_stop(token: str) -> dict:
    """Stop a job window by token using job-stop."""
    repo_bin = Path(__file__).resolve().parents[1] / "bin"
    job_stop = repo_bin / "job-stop"
    if not job_stop.exists():
        raise RuntimeError(f"job-stop not found at {job_stop}")
    import subprocess
    env = os.environ.copy()
    env.setdefault("AGENTD_SESSION", SESSION)
    res = subprocess.run([str(job_stop), token], capture_output=True, text=True, env=env)
    ok = res.returncode == 0
    out = res.stdout + res.stderr
    return {"ok": ok, "output": out.strip()}




@app.resource("job://{token}")
def job_resource(token: str) -> dict:
    return _job_status(token)


@app.resource("log://{token}")
def log_resource(token: str) -> str:
    p = _job_log_path(token)
    if not p.exists():
        return ""
    return _read_text(p)


# Note: FastMCP (current version) does not provide a notify_resources_updated helper.
# Targeting is Self-only: the MCP server must run inside tmux; all notifications
# go back to that origin pane.


if __name__ == "__main__":
    # STDIO server
    app.run()
