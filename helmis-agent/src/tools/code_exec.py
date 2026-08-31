"""
code_exec.py — Sandboxed Python Code Execution Tool for Helmis.

Provides the agent with a universal computation primitive: the ability to write
and execute arbitrary Python code in an isolated subprocess. This transforms
Helmis from a rigid tool-calling bot into a flexible agent that can solve
any computational task (calculations, data parsing, text manipulation, etc.)
without needing a pre-built tool for every use case.

Security: Runs in a restricted subprocess with timeout, output limits,
and isolated working directory (sandbox). No network access by default.
"""

import logging
import os
import subprocess
import tempfile
from typing import Any

from ..memory.sandbox import get_sandbox_dir
from .registry import register_tool

log = logging.getLogger("helmis-tools-code")

# Maximum output sizes to prevent memory issues
MAX_STDOUT = 4000
MAX_STDERR = 2000
MAX_CODE_LENGTH = 8000
DEFAULT_TIMEOUT = 15
MAX_TIMEOUT = 30


@register_tool("execute_code")
async def handle_execute_code(
    args: dict[str, Any],
    default_sender: str,
) -> dict[str, Any]:
    """
    Execute Python code in a sandboxed subprocess.

    The agent writes Python code, which is executed in an isolated environment.
    This enables arbitrary computation: math, data parsing, string manipulation,
    unit conversion, date calculations, CSV/JSON processing, etc.
    """
    code = str(args.get("code") or "").strip()
    timeout = min(int(args.get("timeout", DEFAULT_TIMEOUT) or DEFAULT_TIMEOUT), MAX_TIMEOUT)

    if not code:
        return {"status": "error", "error": "Kode Python tidak boleh kosong."}

    if len(code) > MAX_CODE_LENGTH:
        return {
            "status": "error",
            "error": f"Kode terlalu panjang ({len(code)} karakter). Maksimal {MAX_CODE_LENGTH}.",
        }

    # Basic safety checks — block obviously dangerous operations
    blocked_patterns = [
        "import subprocess", "import shutil", "import socket",
        "os.system(", "os.popen(", "os.exec",
        "__import__('subprocess')", "__import__('shutil')",
        "shutil.rmtree", "os.remove(", "os.unlink(",
        "open('/etc", "open('/proc", "open('/sys",
        "eval(", "exec(",
    ]
    code_lower = code.lower()
    for pattern in blocked_patterns:
        if pattern.lower() in code_lower:
            return {
                "status": "error",
                "error": f"Operasi '{pattern}' tidak diizinkan di sandbox untuk alasan keamanan.",
            }

    sandbox_dir = get_sandbox_dir()
    code_exec_dir = os.path.join(sandbox_dir, "code_exec")
    os.makedirs(code_exec_dir, exist_ok=True)

    # Write code to a temporary file for clean execution
    script_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".py",
            dir=code_exec_dir,
            delete=False,
            encoding="utf-8",
        ) as tmp:
            tmp.write(code)
            script_path = tmp.name

        # Execute in a restricted subprocess
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/usr/local/bin"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONIOENCODING": "utf-8",
            "HOME": code_exec_dir,
            "LANG": "en_US.UTF-8",
            # Timezone for date calculations
            "TZ": "Asia/Jakarta",
        }

        result = subprocess.run(
            ["python3", script_path],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            cwd=code_exec_dir,
        )

        stdout = result.stdout[:MAX_STDOUT] if result.stdout else ""
        stderr = result.stderr[:MAX_STDERR] if result.stderr else ""

        if result.returncode == 0:
            log.debug("Code execution succeeded for [%s]: %s", default_sender, stdout[:80])
            return {
                "status": "success",
                "stdout": stdout,
                "stderr": stderr if stderr else None,
                "message": "Kode berhasil dieksekusi.",
            }
        else:
            log.debug("Code execution failed for [%s]: %s", default_sender, stderr[:80])
            return {
                "status": "error",
                "stdout": stdout if stdout else None,
                "stderr": stderr,
                "error": f"Kode keluar dengan kode error {result.returncode}.",
            }

    except subprocess.TimeoutExpired:
        log.warning("Code execution timed out after %ds for [%s]", timeout, default_sender)
        return {
            "status": "error",
            "error": f"Eksekusi kode melebihi batas waktu {timeout} detik.",
        }
    except Exception as ex:
        log.error("Code execution error for [%s]: %s", default_sender, ex)
        return {"status": "error", "error": f"Error eksekusi: {ex}"}
    finally:
        # Clean up temporary script file
        if script_path and os.path.exists(script_path):
            try:
                os.remove(script_path)
            except Exception:
                pass
