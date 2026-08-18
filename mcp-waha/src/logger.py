"""
logger.py — Standard, concise agentic logger for Helmis.
Follows standard Python logging format with zero emojis and total noise suppression.
"""

import json
import logging
import os
import sys
import time
from typing import Any

# Standard ANSI Color Palette
C_RESET = "\033[0m"
C_DIM = "\033[2m"
C_CYAN = "\033[36m"
C_GREEN = "\033[32m"
C_YELLOW = "\033[33m"
C_MAGENTA = "\033[35m"
C_GRAY = "\033[90m"


class CleanLogFormatter(logging.Formatter):
    """Clean standard format: HH:MM:SS [LEVEL] name: message"""

    def format(self, record: logging.LogRecord) -> str:
        t_str = self.formatTime(record, "%H:%M:%S")
        lvl = record.levelname

        if lvl == "INFO":
            badge = f"{C_CYAN}[INFO]{C_RESET}"
        elif lvl == "WARNING":
            badge = f"{C_YELLOW}[WARN]{C_RESET}"
        elif lvl == "ERROR":
            badge = f"{C_MAGENTA}[ERROR]{C_RESET}"
        else:
            badge = f"{C_GRAY}[{lvl}]{C_RESET}"

        return f"{C_GRAY}{t_str}{C_RESET} {badge} {C_DIM}{record.name}:{C_RESET} {record.getMessage()}"


class NoHealthLogFilter(logging.Filter):
    """Completely filters out /health, ping, and scheduler tick spam."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        if (
            "/health" in msg
            or "GET /health" in msg
            or "GET /ping" in msg
            or "POST /webhooks/scheduler" in msg
            or "Evaluating proactive reminders" in msg
            or "No reminders due" in msg
        ):
            return False
        return True


def setup_logging() -> None:
    """Configure root logger with clean formatter and silence third-party chatty loggers."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(CleanLogFormatter())
    handler.addFilter(NoHealthLogFilter())

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers = [handler]

    # Completely silence external libraries
    for name in (
        "httpx",
        "httpcore",
        "uvicorn",
        "uvicorn.access",
        "uvicorn.error",
        "asyncio",
        "starlette",
    ):
        lgr = logging.getLogger(name)
        lgr.setLevel(logging.CRITICAL)
        lgr.propagate = False
        lgr.handlers.clear()

    try:
        import uvicorn.config

        if hasattr(uvicorn.config, "LOGGING_CONFIG"):
            uvicorn.config.LOGGING_CONFIG["loggers"]["uvicorn.access"]["handlers"] = []
            uvicorn.config.LOGGING_CONFIG["loggers"]["uvicorn.access"]["level"] = "CRITICAL"
            uvicorn.config.LOGGING_CONFIG["loggers"]["uvicorn.access"]["propagate"] = False
    except Exception:
        pass


setup_logging()

log = logging.getLogger("helmis")
TRACES_DIR = os.environ.get("HELMIS_DATA_DIR", "data")
TRACES_FILE = os.path.join(TRACES_DIR, "agent_traces.jsonl")


class AgentTurnTracer:
    """Tracks turn lifecycle and logs concise standard lines."""

    def __init__(self, sender_name: str, chat_id: str, message_text: str, has_media: bool = False):
        self.sender_name = sender_name
        self.chat_id = chat_id
        self.message_text = message_text
        self.has_media = has_media
        self.start_time = time.time()
        self.steps: list[dict[str, Any]] = []
        self.final_reply: str | None = None
        self.status: str = "running"

    def log_incoming(self) -> None:
        media_str = " (media attached)" if self.has_media else ""
        preview = self.message_text.replace("\n", " ").strip()
        if len(preview) > 90:
            preview = preview[:90] + "..."
        log.info("[%s] In: \"%s\"%s", self.sender_name, preview, media_str)

    def log_step(
        self,
        step: int,
        max_steps: int,
        model_name: str,
        tool_call: dict[str, Any] | None = None,
        tool_result: Any = None,
        final_text: str | None = None,
    ) -> None:
        elapsed = (time.time() - self.start_time) * 1000
        step_info = {
            "step": step,
            "model": model_name,
            "elapsed_ms": round(elapsed, 1),
            "tool_call": tool_call,
            "tool_result": tool_result,
            "final_text": final_text,
        }
        self.steps.append(step_info)

        if tool_call:
            func = tool_call.get("name")
            args = tool_call.get("args", {})
            args_str = json.dumps(args, ensure_ascii=False)
            if len(args_str) > 80:
                args_str = args_str[:80] + "..."

            res_str = json.dumps(tool_result, ensure_ascii=False) if tool_result is not None else ""
            if len(res_str) > 80:
                res_str = res_str[:80] + "..."

            log.info(
                "[%s] Step %d/%d: %s(%s) -> %s (%dms)",
                self.sender_name,
                step,
                max_steps,
                func,
                args_str,
                res_str,
                int(elapsed),
            )

    def log_completed(self, reply_text: str | None, status: str = "completed") -> None:
        self.final_reply = reply_text
        self.status = status
        total_time = (time.time() - self.start_time) * 1000

        if reply_text and reply_text not in ("[NO_REPLY]", "NO_REPLY", "None"):
            preview = reply_text.replace("\n", " ").strip()
            if len(preview) > 100:
                preview = preview[:100] + "..."
            log.info(
                "[%s] Reply (%dms, %d step%s): \"%s\"",
                self.sender_name,
                int(total_time),
                len(self.steps),
                "s" if len(self.steps) > 1 else "",
                preview,
            )
        else:
            log.info(
                "[%s] Silent turn (no reply needed, %dms)",
                self.sender_name,
                int(total_time),
            )

        self._save_trace_to_disk(total_time)

    def _save_trace_to_disk(self, total_time_ms: float) -> None:
        try:
            os.makedirs(TRACES_DIR, exist_ok=True)
            record = {
                "timestamp": int(time.time()),
                "sender": self.sender_name,
                "chat_id": self.chat_id,
                "input_text": self.message_text,
                "has_media": self.has_media,
                "total_ms": round(total_time_ms, 1),
                "steps_count": len(self.steps),
                "steps": self.steps,
                "final_reply": self.final_reply,
                "status": self.status,
            }
            with open(TRACES_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            pass
