"""
logger.py — Clean, high-visibility developer logging and structured agent tracer.
Zero emojis, strict professional ANSI colors, structured alignment, and noise filtering.
"""

import json
import logging
import os
import sys
import time
from typing import Any

# ANSI Color Codes
C_RESET = "\033[0m"
C_BOLD = "\033[1m"
C_DIM = "\033[2m"
C_BLUE = "\033[34m"
C_CYAN = "\033[36m"
C_GREEN = "\033[32m"
C_YELLOW = "\033[33m"
C_MAGENTA = "\033[35m"
C_GRAY = "\033[90m"


class CleanLogFormatter(logging.Formatter):
    """Custom log formatter with clean spacing and subtle timestamps."""

    def format(self, record: logging.LogRecord) -> str:
        t_str = self.formatTime(record, "%H:%M:%S")
        level = record.levelname
        name = record.name

        if level == "INFO":
            lvl_badge = f"{C_CYAN}[INFO]{C_RESET}"
        elif level == "WARNING":
            lvl_badge = f"{C_YELLOW}[WARN]{C_RESET}"
        elif level == "ERROR":
            lvl_badge = f"{C_MAGENTA}[ERROR]{C_RESET}"
        else:
            lvl_badge = f"{C_GRAY}[{level}]{C_RESET}"

        msg = record.getMessage()
        return f"{C_GRAY}{t_str}{C_RESET} {lvl_badge} {C_DIM}{name}:{C_RESET} {msg}"


def setup_clean_logging() -> None:
    """Configure root loggers and suppress noisy third-party libraries."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(CleanLogFormatter())

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers = [handler]

    # Silence chatty libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("starlette").setLevel(logging.WARNING)


# Run setup immediately on import
setup_clean_logging()


TRACES_DIR = os.environ.get("HELMIS_DATA_DIR", "data")
TRACES_FILE = os.path.join(TRACES_DIR, "agent_traces.jsonl")


class AgentTurnTracer:
    """Tracks and streams formatted agent execution turns to developer terminal."""

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
        media_str = " [ATTACHMENT]" if self.has_media else ""
        border = "=" * 70
        print(f"\n{C_BLUE}{border}{C_RESET}")
        print(f"{C_BOLD}{C_CYAN}INCOMING TURN{C_RESET} | Sender: {C_BOLD}{self.sender_name}{C_RESET} | Chat: {self.chat_id}{media_str}")
        print(f"{C_DIM}Message:{C_RESET} {self.message_text}")
        print(f"{C_BLUE}{'-' * 70}{C_RESET}")
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

            print(f"{C_YELLOW}[STEP {step}/{max_steps}]{C_RESET} {C_DIM}({model_name} in {elapsed:.0f}ms){C_RESET}")
            print(f"  {C_BOLD}Tool Invocation:{C_RESET} {C_GREEN}{func}{C_RESET}")
            print(f"  {C_DIM}Arguments      :{C_RESET} {args_str}")
            print(f"  {C_DIM}Result         :{C_RESET} {res_str}")
            print(f"{C_GRAY}{'-' * 70}{C_RESET}")
        elif final_text:
            preview = final_text.replace("\n", " ")
            if len(preview) > 160:
                preview = preview[:160] + "..."
            print(f"{C_YELLOW}[STEP {step}/{max_steps}]{C_RESET} {C_DIM}({model_name} in {elapsed:.0f}ms){C_RESET}")
            print(f"  {C_BOLD}Model Output   :{C_RESET} {preview}")
            print(f"{C_GRAY}{'-' * 70}{C_RESET}")
        sys.stdout.flush()

    def log_completed(self, reply_text: str | None, status: str = "completed") -> None:
        self.final_reply = reply_text
        self.status = status
        total_time = (time.time() - self.start_time) * 1000
        border = "=" * 70

        if reply_text and reply_text not in ("[NO_REPLY]", "NO_REPLY", "None"):
            print(f"{C_BOLD}{C_GREEN}DISPATCH SUCCESS{C_RESET} | Latency: {total_time:.0f}ms | Total Steps: {len(self.steps)}")
            print(f"{C_BOLD}Sent Text:{C_RESET}\n{reply_text}")
            print(f"{C_BLUE}{border}{C_RESET}\n")
        else:
            print(f"{C_DIM}DISPATCH SILENT (No WhatsApp reply required) | Latency: {total_time:.0f}ms{C_RESET}")
            print(f"{C_BLUE}{border}{C_RESET}\n")
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
        except Exception as e:
            logging.getLogger("helmis-trace").warning("Could not persist trace record: %s", e)
