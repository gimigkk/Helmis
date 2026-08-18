"""
logger.py — Agentic step logger and execution tracer for Helmis.
Provides a structured tree-style agentic developer trace in terminal logs.
Zero emojis, strict professional ANSI colors, structured alignment, and noise filtering.
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


class HealthFilter(logging.Filter):
    """Filters out /health and uvicorn access ping logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        if "/health" in msg or "GET /health" in msg or "POST /webhooks/scheduler" in msg:
            return False
        return True


class CleanLogFormatter(logging.Formatter):
    """Custom log formatter with clean spacing and subtle badges."""

    def format(self, record: logging.LogRecord) -> str:
        t_str = self.formatTime(record, "%H:%M:%S")
        level = record.levelname
        name = record.name

        if level == "INFO":
            badge = f"{CYAN}[INFO]{RESET}"
        elif level == "WARNING":
            badge = f"{YELLOW}[WARN]{RESET}"
        elif level == "ERROR":
            badge = f"{MAGENTA}[ERROR]{RESET}"
        else:
            badge = f"{GRAY}[{level}]{RESET}"

        msg = record.getMessage()
        return f"{GRAY}{t_str}{RESET} {badge} {DIM}{name}:{RESET} {msg}"


def setup_clean_logging() -> None:
    """Configure root loggers and suppress noisy third-party libraries."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(CleanLogFormatter())
    handler.addFilter(HealthFilter())

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers = [handler]

    # Silence chatty libraries
    for name in ("httpx", "httpcore", "uvicorn", "uvicorn.access", "uvicorn.error", "asyncio", "starlette"):
        lg = logging.getLogger(name)
        lg.setLevel(logging.WARNING)
        lg.propagate = False


# Run setup immediately on import
setup_clean_logging()

TRACES_DIR = os.environ.get("HELMIS_DATA_DIR", "data")
TRACES_FILE = os.path.join(TRACES_DIR, "agent_traces.jsonl")


class AgentTurnTracer:
    """
    Renders a unified, tree-style agentic execution trace in terminal logs.
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
        media_tag = " [MEDIA ATTACHMENT]" if self.has_media else ""
        border = "─" * 72
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

        if tool_call:
            func = tool_call.get("name")
            args = tool_call.get("args", {})
            args_str = json.dumps(args, ensure_ascii=False)
            res_str = json.dumps(tool_result, ensure_ascii=False) if tool_result is not None else ""
            if len(res_str) > 160:
                res_str = res_str[:160] + "..."

            print(f"{CYAN}│{RESET}  {YELLOW}[Step {step}/{max_steps}]{RESET} {DIM}(Model: {model_name} | {elapsed:.0f}ms){RESET}")
            print(f"{CYAN}│{RESET}  ├── {BOLD}Action{RESET} : {GREEN}Tool Call -> {func}{RESET}")
            print(f"{CYAN}│{RESET}  ├── {BOLD}Args  {RESET} : {DIM}{args_str}{RESET}")
            print(f"{CYAN}│{RESET}  └── {BOLD}Result{RESET} : {DIM}{res_str}{RESET}")
            print(f"{CYAN}│{RESET}")
        elif final_text:
            preview = final_text.replace("\n", " ")
            if len(preview) > 160:
                preview = preview[:160] + "..."
            print(f"{CYAN}│{RESET}  {YELLOW}[Step {step}/{max_steps}]{RESET} {DIM}(Model: {model_name} | {elapsed:.0f}ms){RESET}")
            print(f"{CYAN}│{RESET}  └── {BOLD}Output{RESET} : \"{preview}\"")
            print(f"{CYAN}│{RESET}")
        sys.stdout.flush()

    def log_completed(self, reply_text: str | None, status: str = "completed") -> None:
        self.final_reply = reply_text
        self.status = status
        total_time = (time.time() - self.start_time) * 1000
        border = "─" * 72

        if reply_text and reply_text not in ("[NO_REPLY]", "NO_REPLY", "None"):
            print(f"{CYAN}│{RESET}  {BOLD}[STATUS]{RESET} : {GREEN}DISPATCHED TO WHATSAPP{RESET} {DIM}(Latency: {total_time:.0f}ms | Steps: {len(self.steps)}){RESET}")
            print(f"{CYAN}│{RESET}  {BOLD}Reply  {RESET} : \"{reply_text.replace(chr(10), ' ')}\"")
            print(f"{CYAN}└── [AGENT TURN END] {border[:50]}{RESET}\n")
        else:
            print(f"{CYAN}│{RESET}  {BOLD}[STATUS]{RESET} : {DIM}SILENT (No chat reply needed | Latency: {total_time:.0f}ms){RESET}")
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
