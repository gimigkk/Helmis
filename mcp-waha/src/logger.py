"""
logger.py — High-visibility developer tracer and structured agent stream logger.
Provides formatted terminal logging and persistent execution traces.
"""

import json
import logging
import os
import time
from typing import Any

# Configure root logger format
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# Suppress noisy external library logs
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

log = logging.getLogger("helmis-trace")

TRACES_DIR = os.environ.get("HELMIS_DATA_DIR", "data")
TRACES_FILE = os.path.join(TRACES_DIR, "agent_traces.jsonl")


# ANSI Color Codes for Dev Terminal
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
MAGENTA = "\033[95m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


class AgentTurnTracer:
    """Tracks a single agent turn lifecycle and prints high-visibility traces."""

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
        print(
            f"\n{BOLD}{CYAN}┌── 📩 INCOMING WHATSAPP MESSAGE ──────────────────────────────────────{RESET}\n"
            f"{CYAN}│{RESET} {BOLD}From:{RESET} [{self.sender_name}] in ({self.chat_id}){media_tag}\n"
            f"{CYAN}│{RESET} {BOLD}Text:{RESET} \"{self.message_text}\"\n"
            f"{CYAN}├──{RESET}"
        )

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
            args_str = json.dumps(tool_call.get("args", {}), ensure_ascii=False)
            res_str = json.dumps(tool_result, ensure_ascii=False) if tool_result is not None else ""
            print(
                f"{CYAN}│{RESET} 🧠 {BOLD}Step {step}/{max_steps}{RESET} {DIM}({model_name}, {elapsed:.0f}ms){RESET}\n"
                f"{CYAN}│{RESET}    {YELLOW}🛠️  TOOL:{RESET} {BOLD}{func}{RESET}\n"
                f"{CYAN}│{RESET}    {DIM}ARGS:{RESET} {args_str}\n"
                f"{CYAN}│{RESET}    {GREEN}📦 RES :{RESET} {res_str[:120]}{'...' if len(res_str) > 120 else ''}\n"
                f"{CYAN}├──{RESET}"
            )
        elif final_text:
            print(
                f"{CYAN}│{RESET} 🧠 {BOLD}Step {step}/{max_steps}{RESET} {DIM}({model_name}, {elapsed:.0f}ms){RESET}\n"
                f"{CYAN}│{RESET}    {GREEN}💬 SYNTHESIS:{RESET} \"{final_text[:140]}{'...' if len(final_text) > 140 else ''}\"\n"
                f"{CYAN}├──{RESET}"
            )

    def log_completed(self, reply_text: str | None, status: str = "completed") -> None:
        self.final_reply = reply_text
        self.status = status
        total_time = (time.time() - self.start_time) * 1000

        if reply_text and reply_text not in ("[NO_REPLY]", "NO_REPLY", "None"):
            print(
                f"{CYAN}│{RESET} {BOLD}{GREEN}🚀 DISPATCHED TO WHATSAPP{RESET} {DIM}(Total Latency: {total_time:.0f}ms, Steps: {len(self.steps)}){RESET}\n"
                f"{CYAN}│{RESET} {reply_text.replace(chr(10), chr(10) + CYAN + '│ ' + RESET)}\n"
                f"{BOLD}{CYAN}└──────────────────────────────────────────────────────────────────────{RESET}\n"
            )
        else:
            print(
                f"{CYAN}│{RESET} {DIM}🔇 SILENT TURN — No message sent (Total Latency: {total_time:.0f}ms){RESET}\n"
                f"{BOLD}{CYAN}└──────────────────────────────────────────────────────────────────────{RESET}\n"
            )

        # Save trace asynchronously to disk
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
            log.warning("Could not persist trace record: %s", e)
