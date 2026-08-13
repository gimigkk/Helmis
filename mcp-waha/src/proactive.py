"""
proactive.py — Proactive reminder evaluator and scheduler tick handler.
"""

import json
import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from .agent import GEMINI_KEYS, GEMINI_MODELS, get_next_gemini_key
from .client import WahaClient
from .memory import load_memory, save_memory

log = logging.getLogger("helmis-proactive")

GILANG_PHONE = (
    os.environ.get("GILANG_PHONE", "6281932062070")
    .replace("+", "")
    .replace(" ", "")
    .replace("-", "")
)
BUNGA_PHONE = (
    os.environ.get("BUNGA_PHONE", "6281398971445")
    .replace("+", "")
    .replace(" ", "")
    .replace("-", "")
)


async def handle_proactive_scheduler_tick(client: WahaClient) -> None:
    """Evaluate due tasks and send proactive WhatsApp reminders to Gilang and Bunga."""
    log.info("Scheduler tick: Evaluating proactive reminders from disk storage...")
    mem = load_memory()
    tasks = mem.get("tasks", [])
    if not tasks:
        log.debug("No tasks in memory to evaluate.")
        return

    # Filter for unreminded pending tasks
    unreminded = [t for t in tasks if t.get("status") == "pending" and not t.get("reminded")]
    if not unreminded:
        log.debug("No unreminded pending tasks found.")
        return

    now_str = datetime.now(ZoneInfo("Asia/Jakarta")).strftime("%A, %d %B %Y - %H:%M WIB")

    prompt = f"""
Current time in Jakarta: {now_str}
Tasks in storage:
{json.dumps(unreminded, indent=2)}

Task: Identify any pending task that is due within the next 30 minutes, or due right now (e.g. today or overdue), and has NOT been reminded yet (i.e. does not have "reminded": true).
If there are tasks that need a proactive reminder right now, output a JSON array of objects:
[
  {{
    "title": "exact task title",
    "assignee": "Gilang or Bunga",
    "message": "Concise WhatsApp reminder text in Indonesian with ZERO EMOJIS, e.g. 'Halo Gilang, pengingat: *[task title]* (Waktu: [due]).'"
  }}
]
If no reminders are due right now, output exactly: []
Only output valid JSON, nothing else.
"""
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"},
    }

    response_text = ""
    for model in GEMINI_MODELS:
        for _ in range(len(GEMINI_KEYS) or 1):
            api_key = get_next_gemini_key()
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            try:
                async with httpx.AsyncClient(timeout=30.0) as http_client:
                    resp = await http_client.post(url, json=payload)
                    if resp.status_code == 200:
                        candidates = resp.json().get("candidates", [])
                        if candidates:
                            response_text = (
                                candidates[0]
                                .get("content", {})
                                .get("parts", [{}])[0]
                                .get("text", "")
                            )
                            break
                    elif resp.status_code == 429:
                        continue
                    elif resp.status_code == 404:
                        break
            except Exception as e:
                log.error("Proactive reminder evaluation HTTP error on %s: %s", model, e)

        if response_text:
            break

    if not response_text:
        return

    try:
        reminders = json.loads(response_text)
        if not isinstance(reminders, list) or not reminders:
            log.info("No reminders due at this tick.")
            return

        for item in reminders:
            title = item.get("title")
            assignee = str(item.get("assignee", "Gilang"))
            msg_text = item.get("message")
            if not msg_text:
                continue

            target_phone = GILANG_PHONE if "bunga" not in assignee.lower() else BUNGA_PHONE
            target_jid = f"{target_phone}@c.us"

            log.info("Sending proactive reminder to %s (%s): %s", assignee, target_jid, msg_text)
            await client.send_message(chat_id=target_jid, text=msg_text)

            # Mark task as reminded in memory and log activity
            for t in tasks:
                if t.get("title", "").lower() == str(title).lower():
                    t["reminded"] = True
                    t["reminded_at"] = now_str

            from .memory import log_activity

            log_activity(f"Proactive reminder sent to {assignee} for '{title}': \"{msg_text}\"")

        save_memory(mem)
        log.info("Proactive reminders successfully sent and saved to disk.")
    except Exception as ex:
        log.error("Failed to parse or deliver proactive reminders: %s", ex)
