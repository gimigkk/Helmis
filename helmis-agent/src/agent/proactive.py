"""
proactive.py — Polymorphic Proactive Job Dispatcher & Reminder Evaluator.

Supports:
1. Polymorphic Scheduled Bot Jobs:
   - ToolJobExecutor (Direct dynamic dispatch of any TOOL_REGISTRY tool)
   - AgentLoopJobExecutor (Autonomous Gemini ReAct reasoning loop execution)
2. Human Task Lifecycle:
   - Stage 1: Dynamic Kickoff Preparation Buffer (e.g. 15m - 120m before deadline)
   - Stage 2: Final Deadline Alert at due time
   - Urgent 10-Minute Nag Escalation Loop (with 30m Partner Cross-Alert & 60m Stand-Down)
"""

import asyncio
import logging
import os
import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..memory.store import load_memory, log_activity, parse_due_timestamp, save_memory
from ..tools.registry import execute_tool_call
from ..whatsapp.client import WahaClient

log = logging.getLogger("helmis-proactive")
TZ = ZoneInfo("Asia/Jakarta")


async def _delayed_action_runner(task_title: str, delay_sec: float, client: WahaClient) -> None:
    """In-process high-precision countdown timer for near-horizon scheduled actions (<10 mins)."""
    try:
        log.info("Near-horizon countdown started for '%s' (delay: %.1fs)", task_title, delay_sec)
        await asyncio.sleep(delay_sec)
        mem = load_memory()
        t = next((x for x in mem.get("tasks", []) if x.get("title") == task_title), None)
        if t and str(t.get("status", "pending")).lower() == "pending":
            now_dt = datetime.now(TZ)
            now_str = now_dt.strftime("%A, %d %B %Y - %H:%M WIB")
            dispatched = await dispatch_scheduled_action(client=client, task=t, now_str=now_str)
            if dispatched:
                save_memory(mem)
                log.info("Near-horizon timer successfully executed and saved for '%s'", task_title)
    except Exception as e:
        log.error("Error in near-horizon timer for '%s': %s", task_title, e)


def spawn_near_horizon_timer(task: dict[str, Any], client: WahaClient | None) -> None:
    """If scheduled action is due within next 10 minutes (<= 600s), spawn millisecond-precise in-process timer."""
    if not client:
        return
    due_str = task.get("due", "")
    due_ts = parse_due_timestamp(due_str)
    if due_ts == float("inf"):
        return
    now_ts = datetime.now(TZ).timestamp()
    delay_sec = max(0.0, due_ts - now_ts)
    if delay_sec <= 600:  # <= 10 minutes away
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_delayed_action_runner(task.get("title", ""), delay_sec, client))
            log.info("Spawned exact-second timer for '%s' (in %.1f seconds)", task.get("title"), delay_sec)
        except RuntimeError:
            pass


def normalize_chat_target(raw_id: str, default_suffix: str = "@c.us") -> str:
    """Safely format phone number or JID into a valid WhatsApp recipient."""
    if not raw_id:
        return ""
    clean = raw_id.strip()
    if "@" in clean:
        return clean
    clean = clean.replace("+", "").replace(" ", "").replace("-", "")
    if clean.startswith("0"):
        clean = "62" + clean[1:]
    return f"{clean}{default_suffix}"


async def send_reminder_to_recipient(
    client: WahaClient,
    assignee: str,
    text: str,
    is_cross_alert: bool = False,
) -> None:
    """Route human reminder text to the appropriate WhatsApp chat (DM or Trio Group)."""
    trio_group_jid = os.environ.get("TRIO_GROUP_JID", "").strip()
    gilang_raw = os.environ.get("GILANG_PHONE", "").strip()
    bunga_raw = os.environ.get("BUNGA_PHONE", "").strip()
    assignee_lower = assignee.lower()

    is_both = (
        "both" in assignee_lower
        or "semua" in assignee_lower
        or "shared" in assignee_lower
        or "trio" in assignee_lower
        or ("gilang" in assignee_lower and "bunga" in assignee_lower)
    )

    target_chat: str
    if (is_both or is_cross_alert) and trio_group_jid:
        target_chat = trio_group_jid
    elif "bunga" in assignee_lower:
        target_chat = normalize_chat_target(bunga_raw) or "bunga@c.us"
    else:
        target_chat = normalize_chat_target(gilang_raw) or "gilang@c.us"

    log.info("Dispatching reminder to %s: %s", target_chat, text)
    await client.send_message(chat_id=target_chat, text=text)


async def dispatch_scheduled_action(
    client: WahaClient,
    task: dict[str, Any],
    now_str: str,
    is_overdue_catchup: bool = False,
) -> bool:
    """
    Polymorphic executor for scheduled bot actions (Helmis tasks):
    1. ToolJobExecutor: Calls any registered tool in TOOL_REGISTRY dynamically.
    2. AgentLoopJobExecutor: Runs autonomous ReAct reasoning turn for dynamic tasks.
    3. Fallback Dispatcher: Extracts text from title or payload and dispatches to target.
    """
    title = task.get("title", "")
    job = task.get("job") or {}
    kind = str(job.get("kind", "")).strip().lower()
    tool_name = str(job.get("tool_name") or job.get("name") or "").strip()
    tool_args = job.get("tool_args") or job.get("args") or {}

    log.info("Executing scheduled action '%s' (kind: %s, tool: %s)...", title, kind, tool_name)
    task["execution_status"] = "running"

    try:
        # -------------------------------------------------------------------------
        # Strategy 1: Dynamic Tool Invocation via universal TOOL_REGISTRY
        # -------------------------------------------------------------------------
        if kind == "tool" or tool_name:
            if not tool_name:
                tool_name = "send_whatsapp_message"

            default_sender = task.get("requester") or "Gilang"
            result = await execute_tool_call(
                func_name=tool_name,
                args=tool_args,
                default_sender=default_sender,
                client=client,
            )

            if result.get("status") == "success":
                task["status"] = "completed"
                task["execution_status"] = "dispatched"
                task["completed_at"] = now_str
                log_activity(f"Executed scheduled tool '{tool_name}' for '{title}'")
                return True
            else:
                err_msg = result.get("error") or "Unknown tool error"
                log.warning("Tool execution error for '%s': %s", title, err_msg)
                task["retry_count"] = int(task.get("retry_count", 0)) + 1
                if task["retry_count"] >= int(task.get("max_retries", 3)):
                    task["status"] = "failed"
                    task["execution_status"] = "failed"
                    task["error_message"] = err_msg
                return True

        # -------------------------------------------------------------------------
        # Strategy 2: Autonomous Agent Turn (Generative / Multi-Step Reasoning)
        # -------------------------------------------------------------------------
        elif kind == "agent" or "prompt" in job:
            from .loop import run_agentic_react_loop

            prompt = str(job.get("prompt") or title)
            target_chat = job.get("target_chat") or job.get("chat_id")
            if not target_chat:
                gilang_raw = os.environ.get("GILANG_PHONE", "").strip()
                target_chat = normalize_chat_target(gilang_raw)

            synthetic_msg = f"[SCHEDULED AUTONOMOUS TASK EXECUTION]\n{prompt}"
            await run_agentic_react_loop(
                client=client,
                sender_name="Helmis Proactive",
                chat_id=target_chat,
                message_text=synthetic_msg,
            )

            task["status"] = "completed"
            task["execution_status"] = "dispatched"
            task["completed_at"] = now_str
            log_activity(f"Executed autonomous agent task for '{title}'")
            return True

        # -------------------------------------------------------------------------
        # Strategy 3: Fallback / Smart Message Extractor
        # -------------------------------------------------------------------------
        else:
            text_to_send = ""
            quotes = re.findall(r'"([^"]*)"', title)
            if quotes:
                text_to_send = quotes[0]
            elif ":" in title:
                text_to_send = title.split(":", 1)[1].strip()
            else:
                text_to_send = title

            target_phone = os.environ.get("GILANG_PHONE", "").strip()
            target_chat = normalize_chat_target(target_phone)
            prefix = "[Pesan Terjadwal Tertunda]: " if is_overdue_catchup else ""
            await client.send_message(chat_id=target_chat, text=f"{prefix}{text_to_send}")

            task["status"] = "completed"
            task["execution_status"] = "dispatched"
            task["completed_at"] = now_str
            log_activity(f"Dispatched scheduled message for '{title}'")
            return True

    except Exception as exec_err:
        log.error("Fatal error executing scheduled action '%s': %s", title, exec_err)
        task["retry_count"] = int(task.get("retry_count", 0)) + 1
        if task["retry_count"] >= int(task.get("max_retries", 3)):
            task["status"] = "failed"
            task["execution_status"] = "failed"
            task["error_message"] = str(exec_err)
        return True


async def handle_proactive_scheduler_tick(client: WahaClient) -> None:
    """
    Evaluate pending tasks on each scheduler tick (every ~1-5 minutes):
    1. Scheduled Bot Actions (task_type == 'scheduled_action' / assignee == 'Helmis'):
       - Direct polymorphic execution via ToolJobExecutor or AgentLoopJobExecutor.
       - Auto-completes upon successful dispatch.
       - Strictly bypasses human kickoff buffers and 10-minute nag loops.
    2. Human Tasks (task_type == 'reminder'):
       - Stage 1 (Kickoff Buffer): Dispatched at (due - lead_time_minutes).
       - Stage 2 (Final Cutoff / Due Alert): Dispatched at due time.
       - Urgent 10-Minute Nag Loop: Nudges every 10m up to 60m + cross-partner alert at 30m.
    """
    log.info("Scheduler tick: Evaluating proactive reminders and scheduled actions...")
    mem = load_memory()
    tasks = mem.get("tasks", [])
    if not tasks:
        log.debug("No tasks in memory to evaluate.")
        return

    now_dt = datetime.now(TZ)
    now_ts = now_dt.timestamp()
    now_str = now_dt.strftime("%A, %d %B %Y - %H:%M WIB")

    updated_any = False

    for t in tasks:
        try:
            status = str(t.get("status", "pending")).lower()
            if status in ("completed", "failed", "expired"):
                continue

            title = t.get("title", "")
            due_str = t.get("due", "")
            assignee = str(t.get("assignee", "Gilang")).strip()
            task_type = str(t.get("task_type", "reminder")).strip().lower()
            priority = str(t.get("priority", "normal")).strip().lower()
            lead_mins = int(t.get("lead_time_minutes", 0) or 0)
            due_ts = parse_due_timestamp(due_str)

            if due_ts == float("inf"):
                # No parseable deadline, skip automated time-based triggers
                continue

            is_bot_action = (
                task_type in ("scheduled_action", "action", "bot")
                or assignee.lower() == "helmis"
                or bool(t.get("job"))
            )

            # =========================================================================
            # SECTION A: POLYMORPHIC SCHEDULED BOT ACTIONS
            # =========================================================================
            if is_bot_action:
                # 1. Overdue / Downtime Expiration Check (> 2 hours overdue)
                if (now_ts - due_ts) > 7200:
                    t["status"] = "expired"
                    t["execution_status"] = "expired"
                    t["completed_at"] = now_str
                    log.warning("Scheduled action '%s' was overdue by >2h. Marked expired.", title)
                    log_activity(f"Scheduled action expired (>2h): '{title}'")
                    updated_any = True
                    continue

                # 2. Trigger Window: within 2 minutes of due or slightly overdue (<2h)
                if now_ts >= (due_ts - 120):
                    is_late = (now_ts - due_ts) > 300  # More than 5 mins late
                    dispatched = await dispatch_scheduled_action(
                        client=client,
                        task=t,
                        now_str=now_str,
                        is_overdue_catchup=is_late,
                    )
                    if dispatched:
                        updated_any = True
                    continue

                # Not due yet, skip remainder of human reminder logic
                continue

            # =========================================================================
            # SECTION B: HUMAN TASKS & REMINDERS
            # =========================================================================
            kickoff_reminded = bool(t.get("kickoff_reminded"))
            due_reminded = bool(t.get("due_reminded") or t.get("reminded"))
            nudge_count = int(t.get("nudge_count", 0))
            last_nudged_at = float(t.get("last_nudged_at") or 0)
            nudge_stopped = bool(t.get("nudge_stopped"))

            # ---------------------------------------------------------------------
            # 1. STAGE 1: Kickoff Buffer Preparation Ping
            # ---------------------------------------------------------------------
            if lead_mins > 0 and not kickoff_reminded and not due_reminded:
                lead_sec = lead_mins * 60
                if now_ts >= (due_ts - lead_sec - 120) and now_ts < (due_ts - 120):
                    remaining_secs = max(0, int(due_ts - now_ts))
                    remaining_mins = max(1, round(remaining_secs / 60))
                    if remaining_mins >= 60:
                        rem_hrs = remaining_mins // 60
                        rem_mins = remaining_mins % 60
                        lead_text = (
                            f"{rem_hrs} jam {rem_mins} menit"
                            if rem_mins > 0
                            else f"{rem_hrs} jam"
                        )
                    else:
                        lead_text = f"{remaining_mins} menit"

                    msg_text = (
                        f"Halo {assignee}, pengingat persiapan: deadline *{title}* pada {due_str} "
                        f"(sisa {lead_text} lagi). Waktunya mulai persiapan atau pengerjaan ya."
                    )
                    await send_reminder_to_recipient(client, assignee, msg_text)
                    t["kickoff_reminded"] = True
                    t["kickoff_reminded_at"] = now_str
                    log_activity(f"Stage 1 kickoff sent to {assignee} for '{title}' (Lead: {lead_text})")
                    updated_any = True
                    continue

            # ---------------------------------------------------------------------
            # 2. STAGE 2: Final Deadline Alert
            # ---------------------------------------------------------------------
            if not due_reminded:
                # Safeguard: If task is already > 2 hours overdue when first loaded, silently mark reminded
                if (now_ts - due_ts) > 7200:
                    t["due_reminded"] = True
                    t["reminded"] = True
                    t["reminded_at"] = now_str
                    t["nudge_stopped"] = True
                    log.info("Task '%s' was already >2h overdue. Silently marked reminded to avoid false alarms.", title)
                    updated_any = True
                    continue

                # Trigger if within 5 minutes of due or overdue within recent window
                if now_ts >= (due_ts - 300):
                    msg_text = (
                        f"Halo {assignee}, pengingat deadline: *{title}* ({due_str}). "
                        "Jika sudah selesai, kabari Helmis ya."
                    )
                    await send_reminder_to_recipient(client, assignee, msg_text)
                    t["due_reminded"] = True
                    t["reminded"] = True
                    t["reminded_at"] = now_str
                    t["first_reminded_at"] = now_ts
                    t["last_nudged_at"] = now_ts
                    t["nudge_count"] = 1
                    log_activity(f"Stage 2 due reminder sent to {assignee} for '{title}'")
                    updated_any = True
                    continue

            # ---------------------------------------------------------------------
            # 3. URGENT 10-MINUTE NAG ESCALATION LOOP
            # ---------------------------------------------------------------------
            if priority == "urgent" and due_reminded and not nudge_stopped:
                time_since_nudge = (now_ts - last_nudged_at) if last_nudged_at else (now_ts - due_ts)
                if time_since_nudge >= 540:  # ~9 minutes
                    next_count = nudge_count + 1

                    if next_count == 2:
                        msg_text = (
                            f"{assignee}, tugas penting *{title}* belum ada konfirmasi (10 menit lalu). "
                            "Apakah sudah beres atau masih berjalan?"
                        )
                        await send_reminder_to_recipient(client, assignee, msg_text)
                        t["nudge_count"] = 2
                        t["last_nudged_at"] = now_ts
                        log_activity(f"Urgent Nag #2 sent to {assignee} for '{title}'")
                        updated_any = True

                    elif next_count == 3:
                        msg_text = (
                            f"{assignee}, pengingat ke-3 untuk *{title}* (20 menit lewat). "
                            "Mohon konfirmasi statusnya ya."
                        )
                        await send_reminder_to_recipient(client, assignee, msg_text)
                        t["nudge_count"] = 3
                        t["last_nudged_at"] = now_ts
                        log_activity(f"Urgent Nag #3 sent to {assignee} for '{title}'")
                        updated_any = True

                    elif next_count == 4:
                        is_both = (
                            "both" in assignee.lower()
                            or "semua" in assignee.lower()
                            or "shared" in assignee.lower()
                            or "trio" in assignee.lower()
                        )
                        if is_both:
                            msg_text = (
                                f"PENTING: Tugas bersama *{title}* sudah 30 menit lewat dari jadwal "
                                "dan belum ada konfirmasi dari Gilang maupun Bunga. Mohon salah satu bantu cek ya."
                            )
                            await send_reminder_to_recipient(client, assignee, msg_text)
                        else:
                            msg_text = (
                                f"PENTING: {assignee}, tugas *{title}* sudah 30 menit lewat dari jadwal "
                                "dan belum ada konfirmasi."
                            )
                            await send_reminder_to_recipient(client, assignee, msg_text)

                            other_name = "Bunga" if "gilang" in assignee.lower() else "Gilang"
                            cross_msg = (
                                f"PENTING: {other_name}, {assignee} belum ada konfirmasi untuk tugas urgent "
                                f"*{title}* (30 menit lewat). Tolong bantu cek atau bangunkan {assignee} ya."
                            )
                            await send_reminder_to_recipient(client, other_name, cross_msg, is_cross_alert=True)

                        t["nudge_count"] = 4
                        t["last_nudged_at"] = now_ts
                        log_activity(f"Urgent Nag #4 (+ Partner Cross-Alert) sent for '{title}'")
                        updated_any = True

                    elif next_count == 5:
                        msg_text = (
                            f"PENTING: {assignee}, pengingat ke-5 untuk *{title}* (40 menit lewat). "
                            "Mohon kabari statusnya ya."
                        )
                        await send_reminder_to_recipient(client, assignee, msg_text)
                        t["nudge_count"] = 5
                        t["last_nudged_at"] = now_ts
                        log_activity(f"Urgent Nag #5 sent to {assignee} for '{title}'")
                        updated_any = True

                    elif next_count == 6:
                        msg_text = (
                            f"PENTING: {assignee}, pengingat ke-6 untuk *{title}* (50 menit lewat). "
                            "Mohon konfirmasi ya."
                        )
                        await send_reminder_to_recipient(client, assignee, msg_text)
                        t["nudge_count"] = 6
                        t["last_nudged_at"] = now_ts
                        log_activity(f"Urgent Nag #6 sent to {assignee} for '{title}'")
                        updated_any = True

                    elif next_count > 6:
                        msg_text = (
                            f"Helmis menghentikan pengingat otomatis untuk *{title}* (sudah 60 menit tanpa respon). "
                            "Tugas tetap tercatat 'pending' di daftar target."
                        )
                        await send_reminder_to_recipient(client, assignee, msg_text)
                        t["nudge_stopped"] = True
                        t["last_nudged_at"] = now_ts
                        log_activity(f"Urgent Nag stand-down reached (60m) for '{title}'")
                        updated_any = True

        except Exception as task_err:
            log.error("Error evaluating proactive reminder for task '%s': %s", t.get("title"), task_err)

    if updated_any:
        save_memory(mem)
        log.info("Proactive evaluation completed and state saved to disk.")
    else:
        log.debug("No new reminders or nag pings triggered in this tick.")
