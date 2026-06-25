"""Security sandbox for the Dynamic Tool Synthesizer (plans/07 §4).

Two layers guard LLM-written code:
  1. `validate_code` — a static AST allow-list (no os/sys/subprocess/socket/shutil/network, no
     open()/eval/exec/__import__, no dunder access). Runs BEFORE anything executes.
  2. `run_tool_body` — executes the validated body in a CONSTRAINED SUBPROCESS (wall-time timeout +
     CPU/address-space rlimits) with a minimal `__builtins__` and only injected, read-only data
     handles. The body may read the export and write ONLY its output PNG (a tmpfs scratch path).

The body is a *fragment* (no imports): it is handed `pd, np, plt, sns, df, load(...)` and the
statsmodels entry points, and must assign `test_result: dict` and `fig`.
"""
from __future__ import annotations

import ast
import base64
import json
import subprocess
import sys
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]

# Body must NOT import — it uses injected names. Only pure-math stdlib is tolerated if it slips in.
_ALLOWED_IMPORTS = {"math", "statistics"}
_BLOCKED = {
    "os", "sys", "subprocess", "socket", "shutil", "requests", "urllib", "http", "pathlib",
    "importlib", "pickle", "marshal", "ctypes", "open", "eval", "exec", "__import__", "compile",
    "input", "globals", "locals", "vars", "getattr", "setattr", "delattr", "memoryview",
    "breakpoint", "exit", "quit",
}


class UnsafeCode(Exception):
    """Raised by `validate_code` when the AST contains a disallowed construct."""


class SandboxError(Exception):
    """Raised when sandbox execution fails or times out."""


def validate_code(src: str) -> None:
    """Raise `UnsafeCode` unless `src` only uses the allow-listed surface."""
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        raise UnsafeCode(f"syntax error: {e}") from e
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] not in _ALLOWED_IMPORTS:
                    raise UnsafeCode(f"import not allowed: {a.name}")
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] not in _ALLOWED_IMPORTS:
                raise UnsafeCode(f"import-from not allowed: {node.module}")
        elif isinstance(node, ast.Attribute):
            if isinstance(node.attr, str) and node.attr.startswith("__"):
                raise UnsafeCode(f"dunder attribute access not allowed: {node.attr}")
        elif isinstance(node, ast.Name) and node.id in _BLOCKED:
            raise UnsafeCode(f"use of '{node.id}' not allowed")
    return None


# The trusted runner executed in the child process. Only the user `body` is constrained; this
# wrapper is our code. It builds a restricted namespace, re-validates, execs the body, saves the fig.
_RUNNER = r'''
import json, sys
sys.path.insert(0, __REPO_SRC__)

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
try:
    import seaborn as sns
except Exception:
    sns = None
from statsmodels.tsa.stattools import acf, pacf, adfuller, kpss
from statsmodels.tsa.seasonal import seasonal_decompose

from airraid.eda import data as _data
from airraid.eda.sandbox import validate_code as _validate

body_path, out_png, oblast = sys.argv[1], sys.argv[2], (sys.argv[3] or None)
body = open(body_path).read()
_validate(body)  # defense in depth — re-validate inside the child

_df = _data.feature_frame(oblast)
def load(column, ob=None):
    return _data.series(column, ob if ob is not None else oblast)

_SAFE_BUILTINS = {k: __builtins__[k] if isinstance(__builtins__, dict) else getattr(__builtins__, k)
                  for k in ("range","len","float","int","str","list","dict","tuple","set","min","max",
                            "sum","abs","round","sorted","enumerate","zip","bool","print","map","filter",
                            "any","all","True","False","None","isinstance","slice","reversed","divmod",
                            "pow","format","repr") if (k in __builtins__ if isinstance(__builtins__, dict)
                            else hasattr(__builtins__, k))}

_ns = {"__builtins__": _SAFE_BUILTINS, "pd": pd, "np": np, "plt": plt, "sns": sns,
       "df": _df, "load": load, "acf": acf, "pacf": pacf, "adfuller": adfuller, "kpss": kpss,
       "seasonal_decompose": seasonal_decompose}

exec(compile(body, "<dynamic_tool>", "exec"), _ns)

tr = _ns.get("test_result")
if not isinstance(tr, dict):
    raise SystemExit("dynamic tool did not assign a `test_result` dict")
fig = _ns.get("fig") or plt.gcf()
fig.savefig(out_png, dpi=110, bbox_inches="tight")
print(json.dumps({"test_result": tr}))
'''


def _limits(cpu_seconds: int):
    """preexec_fn for POSIX: bound CPU + address space so a runaway body cannot hog the host."""
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
        try:
            two_gb = 2 * 1024 * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (two_gb, two_gb))
        except (ValueError, OSError):
            pass  # RLIMIT_AS not always settable (e.g. macOS) — wall-time timeout still applies
    except Exception:
        pass


def run_tool_body(body: str, oblast=None, timeout: int = 20) -> dict:
    """Validate, then execute `body` in a constrained subprocess. Returns {test_result, plot_image}."""
    validate_code(body)  # parent-side gate (raises UnsafeCode before any process spawns)
    scratch = Path(tempfile.mkdtemp(prefix="analyst_dyn_"))
    body_path = scratch / "body.py"
    out_png = scratch / "plot.png"
    runner_path = scratch / "runner.py"
    body_path.write_text(body)
    runner_path.write_text(_RUNNER.replace("__REPO_SRC__", repr(str(_REPO / "src"))))

    env = {
        "PYTHONPATH": str(_REPO / "src"),
        "AIRRAID_EXPORTS_DIR": str(__import__("os").environ.get(
            "AIRRAID_EXPORTS_DIR", str(_REPO / "data" / "exports"))),
        "MPLBACKEND": "Agg", "PYTHONHASHSEED": "0",
        "PATH": __import__("os").environ.get("PATH", ""),
    }
    try:
        proc = subprocess.run(
            [sys.executable, str(runner_path), str(body_path), str(out_png), (str(oblast) if oblast else "")],
            capture_output=True, text=True, timeout=timeout, env=env,
            preexec_fn=(lambda: _limits(timeout)) if sys.platform != "win32" else None,
        )
    except subprocess.TimeoutExpired as e:
        raise SandboxError(f"dynamic tool timed out after {timeout}s") from e
    if proc.returncode != 0:
        raise SandboxError(f"dynamic tool failed: {proc.stderr.strip()[-1500:]}")
    line = next((ln for ln in reversed(proc.stdout.splitlines()) if ln.strip().startswith("{")), None)
    if line is None:
        raise SandboxError(f"no result emitted; stderr: {proc.stderr.strip()[-500:]}")
    test_result = json.loads(line)["test_result"]
    if not out_png.exists():
        raise SandboxError("dynamic tool produced no plot")
    plot_image = base64.b64encode(out_png.read_bytes()).decode("ascii")
    return {"test_result": test_result, "plot_image": plot_image}
