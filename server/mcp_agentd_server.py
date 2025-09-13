#!/usr/bin/env python3
import asyncio
import json
import os
import re
import shutil
from pathlib import Path
from typing import Optional, Dict, Any, List
import secrets
import datetime as _dt

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


def _auto_session() -> Optional[str]:
    """Pick an automatic session based on recent user activity.

    Priority:
      1) Most recently active tmux client session
      2) Most recently attached session
      3) Most recently created session
    """
    if not _tmux_ok():
        return None
    import subprocess
    # 1) Most recently active client
    try:
        out = subprocess.run(
            [
                "tmux",
                "list-clients",
                "-F",
                "#{client_activity} #{client_session}",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        lines = [l.strip() for l in out.stdout.splitlines() if l.strip()]
        if lines:
            sess = sorted(lines, key=lambda s: int(s.split()[0]), reverse=True)[0].split()[1]
            if sess:
                return sess
    except Exception:
        pass
    # 2) Most recently attached session
    try:
        out = subprocess.run(
            [
                "tmux",
                "list-sessions",
                "-F",
                "#{session_last_attached} #{session_name}",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        pairs = []
        for l in out.stdout.splitlines():
            l = l.strip()
            if not l:
                continue
            ts, name = l.split(maxsplit=1)
            try:
                tsv = int(ts)
            except Exception:
                continue
            if tsv != -1:
                pairs.append((tsv, name))
        if pairs:
            return sorted(pairs, key=lambda x: x[0], reverse=True)[0][1]
    except Exception:
        pass
    # 3) Most recently created session
    try:
        out = subprocess.run(
            [
                "tmux",
                "list-sessions",
                "-F",
                "#{session_created} #{session_name}",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        lines = [l.strip() for l in out.stdout.splitlines() if l.strip()]
        if lines:
            return sorted(lines, key=lambda s: int(s.split()[0]), reverse=True)[0].split()[1]
    except Exception:
        pass
    return None


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
    # Do not force a global log dir here; job-run will prefer the target pane's cwd/mcp_log.
    import subprocess
    # Pre-generate a token so we can surface it (and log commands) immediately
    ts = _dt.datetime.now().strftime("%Y%m%d%H%M%S")
    tok_suffix = secrets.token_hex(3)  # 6 hex chars like agentd_rand
    token = f"job-{ts}-{tok_suffix}"
    env["JOB_TOKEN"] = token

    args = [str(job_run), cmd]
    # Priority (AUTO first when no explicit target):
    #   1) explicit target parameter
    #   2) explicit session/window/pane
    #   3) saved agent pane (~/.agentd/agent_pane)
    #   4) AUTO recent session (cli.0)
    #   5) SELF_PANE (server launched inside tmux)
    #   6) default SESSION:CLI_WINDOW.0
    if target:
        env["JOB_TARGET_PANE"] = target
        session_name = target.split(":", 1)[0] if ":" in target else (session or SESSION)
    elif session:
        w = window or os.environ.get("AGENTD_CLI_WINDOW", CLI_WINDOW)
        p = pane if pane is not None else 0
        session_name = session
        env["JOB_TARGET_PANE"] = f"{session}:{w}.{p}"
    else:
        saved = _read_target()
        if saved and _tmux_pane_exists(saved):
            env["JOB_TARGET_PANE"] = saved
            session_name = saved.split(":", 1)[0]
        else:
            auto = _auto_session()
            if auto:
                session_name = auto
                env["JOB_TARGET_PANE"] = f"{auto}:{CLI_WINDOW}.0"
            elif SELF_PANE:
                session_name = SELF_PANE.split(":", 1)[0]
                env["JOB_TARGET_PANE"] = SELF_PANE
            else:
                # Fall back to default session name; job-run will create if needed
                session_name = SESSION
                env["JOB_TARGET_PANE"] = f"{SESSION}:{CLI_WINDOW}.0"

    # Hint job-run which session to create the window in
    env.setdefault("JOB_SESSION", session_name)
    # Execute job-run and capture token
    # Compute useful view commands before launching
    # Try to predict log path using the target pane's cwd
    log_dir_guess = None
    target_pane = env.get("JOB_TARGET_PANE")
    if target_pane:
        try:
            import subprocess as _sp
            cwd = _sp.run(["tmux", "display-message", "-p", "-t", target_pane, "#{pane_current_path}"], capture_output=True, text=True, check=True).stdout.strip()
            if cwd:
                log_dir_guess = str(Path(cwd) / "mcp_log")
        except Exception:
            log_dir_guess = None
    log_path = str(Path(log_dir_guess or str(LOG_DIR)) / f"{token}.log")
    # Determine execution session consistent with job-run (self|fixed|per_repo)
    exec_mode = env.get("AGENTD_EXEC_SESSION_MODE", os.environ.get("AGENTD_EXEC_SESSION_MODE", "per_repo"))
    exec_session: str
    if exec_mode == "self":
        exec_session = session_name
    elif exec_mode == "fixed":
        exec_session = env.get("AGENTD_EXEC_SESSION", os.environ.get("AGENTD_EXEC_SESSION", "agentexec"))
    else:
        # per_repo (default): exec-<basename of pane cwd>
        try:
            if target_pane:
                import subprocess as _sp
                cwd = _sp.run(["tmux", "display-message", "-p", "-t", target_pane, "#{pane_current_path}"], capture_output=True, text=True, check=True).stdout.strip()
                base = Path(cwd).name if cwd else "exec"
            else:
                base = "exec"
        except Exception:
            base = "exec"
        exec_session = env.get("AGENTD_EXEC_SESSION", f"exec-{base}")

    inside_cmd = f"tmux select-window -t '{exec_session}:{token}'"
    outside_cmd = f"tmux attach -t '{exec_session}' \\; select-window -t '{exec_session}:{token}'"
    tail_cmd = f"tail -f '{log_path}'"

    # Launch the job in the background (non-blocking for the MCP tool)
    import subprocess as _sp
    _sp.Popen(
        args,
        env=env,
        stdout=_sp.DEVNULL,
        stderr=_sp.DEVNULL,
        start_new_session=True,
    )

    return {
        "token": token,
        "session": session_name,
        "exec_session": exec_session,
        "target": env.get("JOB_TARGET_PANE"),
        "log_path": log_path,
        "attach": outside_cmd,
        "view": {
            "tail": tail_cmd,
            "tmux_inside": inside_cmd,
            "tmux_outside": outside_cmd,
        },
    }


@app.tool()
def tmux_stop(token: str, remove_log: bool = False) -> dict:
    """Stop/cleanup a job by token: kill tmux windows and remove metadata files.

    Args:
        token: job token (e.g., 'job-2025...')
        remove_log: also delete ~/.agentd/logs/<token>.log if True
    Returns:
        {"token": str, "cleaned": bool}
    """
    import subprocess
    script = _bin("job-clean")
    if not script.exists():
        raise RuntimeError("job-clean not found")
    args = [str(script), token]
    if remove_log:
        args.append("--remove-log")
    try:
        subprocess.run(args, check=True, capture_output=True, text=True)
        return {"token": token, "cleaned": True}
    except subprocess.CalledProcessError as e:
        return {"token": token, "cleaned": False, "error": e.stderr or e.stdout}


"""
Note: For Self専用ミニマム運用のため、公開ツールは tmux.run のみ。
ログや状態はファイル（mcp_log/ や ~/.agentd/）で確認できます。
必要になれば tmux.status / tmux.logs / tmux.stop を再度公開してください。
"""




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
