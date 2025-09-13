#!/usr/bin/env python3
import os
from pathlib import Path
from typing import Optional, Dict, Any, List
import secrets
import datetime as _dt

from mcp.server.fastmcp import FastMCP

AGENTD_DIR = Path(os.environ.get("AGENTD_DIR", os.path.expanduser("~/.agentd")))
# Prefer repo-local mcp_log, then env AGENTD_LOGDIR, then ~/.agentd/logs
REPO_DIR = Path(__file__).resolve().parents[1]
REPO_LOG_DIR = REPO_DIR / "mcp_log"
ENV_LOG_DIR = Path(os.environ.get("AGENTD_LOGDIR", str(REPO_LOG_DIR)))
HOME_LOG_DIR = AGENTD_DIR / "logs"
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


def _candidate_log_dirs() -> List[Path]:
    # Order: repo mcp_log -> env-provided -> ~/.agentd/logs
    dirs = []
    if REPO_LOG_DIR:
        dirs.append(REPO_LOG_DIR)
    if ENV_LOG_DIR and ENV_LOG_DIR != REPO_LOG_DIR:
        dirs.append(ENV_LOG_DIR)
    if HOME_LOG_DIR:
        dirs.append(HOME_LOG_DIR)
    return dirs


def _job_log_path(token: str) -> Path:
    for d in _candidate_log_dirs():
        p = Path(d) / f"{token}.log"
        if p.exists():
            return p
    # Fallback: default to repo-local mcp_log path (first in list)
    base = _candidate_log_dirs()[0] if _candidate_log_dirs() else HOME_LOG_DIR
    return Path(base) / f"{token}.log"


# (Removed) _shell_quote: not used.


def _list_job_tokens() -> List[str]:
    if not AGENTD_DIR.exists():
        return []
    toks: List[str] = []
    for p in AGENTD_DIR.glob("*.rc"):
        toks.append(p.stem)
    # Include logs without rc as well across all known log dirs
    for d in _candidate_log_dirs():
        if Path(d).exists():
            toks.extend([p.stem for p in Path(d).glob("*.log")])
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


# Removed unused bootstrap helper; pane targeting is resolved dynamically in tmux_run.


# No direct use for self session aside from diagnostics; remove dead helper.


# Removed unused CLI pane helpers.


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

def _active_pane_in_session(session: str) -> Optional[str]:
    if not _tmux_ok():
        return None
    import subprocess
    try:
        out = subprocess.run([
            "tmux", "list-panes", "-t", session, "-F", "#{window_index}.#{pane_index} #{?pane_active,1,0}"
        ], capture_output=True, text=True, check=True)
        lines = [l.strip() for l in out.stdout.splitlines() if l.strip()]
        for l in lines:
            idx, active = l.split()
            if active == "1":
                return f"{session}:{idx}"
        if lines:
            idx = lines[0].split()[0]
            return f"{session}:{idx}"
    except Exception:
        return None
    return None

def _shell_friendly_pane_in_session(session: str) -> Optional[str]:
    """Return a pane in session likely running a shell (bash/zsh/fish/sh), else first pane.
    Format: session:win.pane
    """
    if not _tmux_ok():
        return None
    import subprocess
    try:
        out = subprocess.run([
            "tmux", "list-panes", "-t", session, "-F", "#{window_index}.#{pane_index} #{pane_current_command}"
        ], capture_output=True, text=True, check=True)
        shells = {"bash","zsh","fish","sh","nu"}
        first = None
        for line in out.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            idx, cmd = line.split(maxsplit=1)
            if first is None:
                first = idx
            if cmd in shells:
                return f"{session}:{idx}"
        if first:
            return f"{session}:{first}"
    except Exception:
        return None
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
        # Prefer the active pane of the most recently active session
        pane_target = None
        saved = _read_target()
        if saved and _tmux_pane_exists(saved):
            pane_target = saved
        else:
            auto = _auto_session()
            if auto:
                pane_target = _active_pane_in_session(auto)
        if not pane_target and SELF_PANE:
            pane_target = SELF_PANE
        if not pane_target:
            pane_target = f"{SESSION}:{CLI_WINDOW}.0"
        env["JOB_TARGET_PANE"] = pane_target
        session_name = pane_target.split(":", 1)[0]

    # Do NOT force JOB_SESSION here; let job-run decide exec session
    # based on AGENTD_EXEC_SESSION_MODE (default we set to 'self' below).
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
    # Predict log path: prefer target pane's cwd/mcp_log; else repo mcp_log; else ~/.agentd/logs
    base_log_dir = log_dir_guess or (str(REPO_LOG_DIR) if REPO_LOG_DIR else None) or str(HOME_LOG_DIR)
    log_path = str(Path(base_log_dir) / f"{token}.log")
    # Determine execution session consistent with job-run (self|fixed|per_repo)
    exec_mode = env.get("AGENTD_EXEC_SESSION_MODE", "self")
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

    # Execution/session behavior: default to running in the caller's session (self)
    env.setdefault("AGENTD_EXEC_SESSION_MODE", os.environ.get("AGENTD_EXEC_SESSION_MODE", "self"))
    # By default, always notify the initiating (agent) pane.
    # If AGENTD_NOTIFY_FORCE_SHELL=1, reroute to a shell-friendly pane in the same session.
    if env.get("JOB_TARGET_PANE"):
        force_shell = env.get("AGENTD_NOTIFY_FORCE_SHELL", os.environ.get("AGENTD_NOTIFY_FORCE_SHELL", "0"))
        if force_shell == "1":
            try:
                sess = env["JOB_TARGET_PANE"].split(":",1)[0]
                alt = _shell_friendly_pane_in_session(sess)
                env.setdefault("JOB_NOTIFY_PANE", alt or env["JOB_TARGET_PANE"]) 
            except Exception:
                env.setdefault("JOB_NOTIFY_PANE", env["JOB_TARGET_PANE"]) 
        else:
            env.setdefault("JOB_NOTIFY_PANE", env["JOB_TARGET_PANE"]) 

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
        remove_log: also delete the job log from the active log dir if True
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
