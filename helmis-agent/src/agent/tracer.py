"""
tracer.py — Structured turn tracing and formatted logging for Helmis.
"""

import json
import logging
import os
import sys
import time
from typing import Any

# ANSI Color Palette
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
GRAY = "\033[90m"


class CleanLogFormatter(logging.Formatter):
    """Clean standard format: HH:MM:SS [LEVEL] name: message"""

    def format(self, record: logging.LogRecord) -> str:
        t_str = self.formatTime(record, "%H:%M:%S")
        lvl = record.levelname

        if lvl == "INFO":
            badge = f"{CYAN}[INFO]{RESET}"
        elif lvl == "WARNING":
            badge = f"{YELLOW}[WARN]{RESET}"
        elif lvl == "ERROR":
            badge = f"{MAGENTA}[ERROR]{RESET}"
        else:
            badge = f"{GRAY}[{lvl}]{RESET}"

        return f"{GRAY}{t_str}{RESET} {badge} {DIM}{record.name}:{RESET} {record.getMessage()}"


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
    """Configure root logger and completely silence third-party chatty loggers."""
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
    """
    Renders structured, formatted agent steps in terminal logs for effortless debugging.
    """

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
        media_tag = f" {YELLOW}[MEDIA ATTACHED]{RESET}" if self.has_media else ""
        border = "─" * 70
        print(f"\n{CYAN}┌── [AGENT TURN START] {border[:48]}{RESET}")
        print(f"{CYAN}│{RESET}  {BOLD}User   :{RESET} {self.sender_name} {DIM}({self.chat_id}){RESET}{media_tag}")
        print(f"{CYAN}│{RESET}  {BOLD}Input  :{RESET} \"{self.message_text}\"")
        print(f"{CYAN}│{RESET}")
        sys.stdout.flush()

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

        divider = "─" * 50
        print(f"{CYAN}│{RESET}  {YELLOW}── Step {step}/{max_steps} [{model_name} | {elapsed:.0f}ms] {divider[:32]}{RESET}")

        if tool_call:
            func = tool_call.get("name", "")
            args = tool_call.get("args", {})
            args_formatted = json.dumps(args, ensure_ascii=False, indent=2)
            # Indent multi-line args
            args_indented = args_formatted.replace("\n", "\n" + f"{CYAN}│{RESET}           ")

            res_formatted = json.dumps(tool_result, ensure_ascii=False, indent=2) if tool_result is not None else ""
            if len(res_formatted) > 300:
                res_formatted = res_formatted[:300] + "\n... (truncated)"
            res_indented = res_formatted.replace("\n", "\n" + f"{CYAN}│{RESET}           ")

            print(f"{CYAN}│{RESET}  {BOLD}Tool   :{RESET} {GREEN}{func}{RESET}")
            print(f"{CYAN}│{RESET}  {BOLD}Args   :{RESET} {DIM}{args_indented}{RESET}")
            print(f"{CYAN}│{RESET}  {BOLD}Result :{RESET} {DIM}{res_indented}{RESET}")
            print(f"{CYAN}│{RESET}")
        elif final_text:
            output_indented = final_text.strip().replace("\n", "\n" + f"{CYAN}│{RESET}           ")
            print(f"{CYAN}│{RESET}  {BOLD}Output :{RESET} {output_indented}")
            print(f"{CYAN}│{RESET}")
        sys.stdout.flush()

    def log_completed(self, reply_text: str | None, status: str = "completed") -> None:
        self.final_reply = reply_text
        self.status = status
        total_time = (time.time() - self.start_time) * 1000
        border = "─" * 70

        if reply_text and reply_text not in ("[NO_REPLY]", "NO_REPLY", "None"):
            reply_indented = reply_text.strip().replace("\n", "\n" + f"{CYAN}│{RESET}          ")
            print(f"{CYAN}│{RESET}  {GREEN}── Turn Dispatched [{total_time:.0f}ms | {len(self.steps)} step{'s' if len(self.steps) > 1 else ''}] {border[:34]}{RESET}")
            print(f"{CYAN}│{RESET}  {BOLD}Reply :{RESET} {reply_indented}")
            print(f"{CYAN}└── [AGENT TURN END] {border[:50]}{RESET}\n")
        else:
            print(f"{CYAN}│{RESET}  {DIM}── Turn Silent (No WhatsApp reply required | {total_time:.0f}ms) {border[:30]}{RESET}")
            print(f"{CYAN}└── [AGENT TURN END] {border[:50]}{RESET}\n")
        sys.stdout.flush()

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
