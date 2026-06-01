"""d4j_client.py — HTTP client for the ``defects4j_docker_web`` service.

RepairAgent runs natively on the HOST and edits Java files on the host.  Only
validation — ``defects4j checkout / compile / test / info`` — runs inside the
Docker container, through the ``defects4j_docker_web`` webapp.

The agent workspace directory is bind-mounted into the container at
``CONTAINER_WORKSPACE`` (default ``/workspace``), so files the agent writes on
the host are visible to ``defects4j`` inside the container, and what
``defects4j checkout`` produces inside the container is visible to the agent.

Service (Flask, default ``http://localhost:8090``)::

    GET  /health
    POST /api/exec        {"args": [...], "cwd": "..."}  -> {returncode,stdout,stderr}
    POST /api/exec-shell  {"cmd": "...",  "cwd": "..."}   -> {returncode,stdout,stderr}
    POST /api/upload      multipart: file + path         -> {status,path}
    GET  /api/download    ?path=...                      -> binary

Environment variables:
    DEFECTS4J_URL            webapp URL              (default http://localhost:8090)
    D4J_CONTAINER_WORKSPACE  workspace path in cont. (default /workspace)
    D4J_LOCAL_WORKSPACE      host workspace dir      (default ./auto_gpt_workspace)
    DEFECTS4J_CURL_TIMEOUT   request timeout seconds (default 1900)
"""

import logging
import os
from typing import List, Optional, Tuple

import requests

logger = logging.getLogger("repair_agent_d4j")

# ── Module configuration (overridable via env vars or the setters below) ──
D4J_URL = os.getenv("DEFECTS4J_URL", "http://localhost:8090").rstrip("/")
CONTAINER_WORKSPACE = os.getenv("D4J_CONTAINER_WORKSPACE", "/workspace")
HOST_WORKSPACE = os.path.abspath(os.getenv("D4J_LOCAL_WORKSPACE", "auto_gpt_workspace"))
REQUEST_TIMEOUT = int(os.getenv("DEFECTS4J_CURL_TIMEOUT", "1900"))


def set_url(url: str) -> None:
    global D4J_URL
    D4J_URL = url.rstrip("/")


def set_host_workspace(ws: str) -> None:
    """Point the client at the HOST directory that is bind-mounted into the
    container.  Must match ``D4J_LOCAL_WORKSPACE`` in the service's ``.env``."""
    global HOST_WORKSPACE
    HOST_WORKSPACE = os.path.abspath(str(ws))


def set_container_workspace(ws: str) -> None:
    global CONTAINER_WORKSPACE
    CONTAINER_WORKSPACE = ws


# ── Path translation helpers ──

def host_to_container(path: str) -> str:
    """Convert a HOST path to its equivalent CONTAINER path."""
    abs_host = os.path.abspath(path)
    abs_ws = os.path.abspath(HOST_WORKSPACE)
    if abs_host == abs_ws or abs_host.startswith(abs_ws + os.sep):
        return CONTAINER_WORKSPACE + abs_host[len(abs_ws):]
    return path


def container_to_host(path: str) -> str:
    """Convert a CONTAINER path to its equivalent HOST path."""
    if path == CONTAINER_WORKSPACE or path.startswith(CONTAINER_WORKSPACE + "/"):
        return os.path.join(HOST_WORKSPACE, path[len(CONTAINER_WORKSPACE):].lstrip("/"))
    return path


def container_project_dir(folder_name: str) -> str:
    """Return the CONTAINER path of a checked-out bug, e.g. ``/workspace/lang_1_buggy``."""
    return f"{CONTAINER_WORKSPACE}/{folder_name}"


def folder_name_for(project: str, bug_index) -> str:
    """The checkout folder name RepairAgent uses: ``{project}_{index}_buggy``."""
    return "_".join([project.lower(), str(bug_index), "buggy"])


# ── Core HTTP wrappers ──

def health_check() -> bool:
    try:
        resp = requests.get(f"{D4J_URL}/health", timeout=30)
        return resp.status_code == 200
    except Exception as e:  # noqa: BLE001
        logger.error("health_check failed: %s", e)
        return False


def d4j_exec(args: List, cwd: Optional[str] = None) -> Tuple[int, str, str]:
    """Run a ``defects4j`` subcommand inside the container.

    Returns ``(returncode, stdout, stderr)``.
    """
    payload = {"args": [str(a) for a in args], "cwd": cwd or CONTAINER_WORKSPACE}
    logger.debug("d4j_exec: defects4j %s (cwd=%s)",
                 " ".join(payload["args"]), payload["cwd"])
    try:
        resp = requests.post(f"{D4J_URL}/api/exec", json=payload, timeout=REQUEST_TIMEOUT)
        data = resp.json()
        return data.get("returncode", 1), data.get("stdout", ""), data.get("stderr", "")
    except Exception as e:  # noqa: BLE001
        logger.error("d4j_exec failed: %s", e)
        return 1, "", str(e)


def d4j_shell(cmd: str, cwd: Optional[str] = None) -> Tuple[int, str, str]:
    """Run a shell command inside the container.

    Returns ``(returncode, stdout, stderr)``.
    """
    payload = {"cmd": cmd, "cwd": cwd or CONTAINER_WORKSPACE}
    logger.debug("d4j_shell: %s", cmd[:200])
    try:
        resp = requests.post(f"{D4J_URL}/api/exec-shell", json=payload, timeout=REQUEST_TIMEOUT)
        data = resp.json()
        return data.get("returncode", 1), data.get("stdout", ""), data.get("stderr", "")
    except Exception as e:  # noqa: BLE001
        logger.error("d4j_shell failed: %s", e)
        return 1, "", str(e)


def d4j_upload(local_path: str, container_path: str) -> dict:
    """Upload a host file to ``container_path`` inside the container.

    Not needed while the workspace is a shared bind mount; kept for parity
    with the D4C client.
    """
    try:
        with open(local_path, "rb") as f:
            resp = requests.post(
                f"{D4J_URL}/api/upload",
                data={"path": container_path}, files={"file": f}, timeout=120)
        return resp.json()
    except Exception as e:  # noqa: BLE001
        logger.error("d4j_upload failed: %s", e)
        return {"error": str(e)}


def d4j_download(container_path: str, local_path: str) -> bool:
    """Download a container file to ``local_path`` on the host."""
    try:
        resp = requests.get(
            f"{D4J_URL}/api/download", params={"path": container_path}, timeout=120)
        if resp.status_code == 200:
            with open(local_path, "wb") as f:
                f.write(resp.content)
            return True
        return False
    except Exception as e:  # noqa: BLE001
        logger.error("d4j_download failed: %s", e)
        return False


# ── Convenience wrappers for the operations RepairAgent needs ──

def checkout(project: str, bug_index, folder_name: Optional[str] = None) -> Tuple[int, str, str]:
    """``defects4j checkout -p <project> -v <index>b -w /workspace/<folder>``."""
    folder_name = folder_name or folder_name_for(project, bug_index)
    target = container_project_dir(folder_name)
    return d4j_exec(["checkout", "-p", project, "-v", f"{bug_index}b", "-w", target])


def compile_and_test(project: str, bug_index, folder_name: Optional[str] = None) -> Tuple[int, str, str]:
    """Run ``defects4j compile`` then ``defects4j test`` in the bug's checkout dir.

    Equivalent to the original ``cd <dir> && defects4j compile && defects4j test``:
    a non-zero compile short-circuits the test phase.  Each step is a ``/api/exec``
    call (which invokes the service's known ``defects4j`` binary), and the combined
    stdout/stderr is returned so callers can scan it exactly as before.
    """
    folder_name = folder_name or folder_name_for(project, bug_index)
    cdir = container_project_dir(folder_name)

    rc, out, err = d4j_exec(["compile"], cwd=cdir)
    if rc != 0:
        return rc, out, err
    rc_t, out_t, err_t = d4j_exec(["test"], cwd=cdir)
    return rc_t, out + out_t, err + err_t


def info(project: str, bug_index) -> Tuple[int, str, str]:
    """``defects4j info -p <project> -b <index>``."""
    return d4j_exec(["info", "-p", project, "-b", bug_index])
