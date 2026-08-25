"""
proactive.py — Proactive reminder evaluator, 2-stage lead-time buffer, and 10-minute nag escalation engine.
"""

import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from .client import WahaClient
from .memory import load_memory, log_activity, parse_due_timestamp, save_memory

log = logging.getLogger("helmis-proactive")
TZ = ZoneInfo("Asia/Jakarta")

GILANG_PHONE = (
    os.environ.get("GILANG_PHONE", "")
    .replace("+", "")
    .replace(" ", "")
    .replace("-", "")
)
BUNGA_PHONE = (
    os.environ.get("BUNGA_PHONE", "")
    .replace("+", "")
    .replace(" ", "")
    .replace("-", "")
)


async def send_reminder_to_recipient(
    client: WahaClient,
    assignee: str,
    text: str,
    is_cross_alert: bool = False,
) -> None:
    """Route reminder text to the appropriate WhatsApp chat (DM or Trio Group)."""
    trio_group_jid = os.environ.get("TRIO_GROUP_JID", "")
    gilang_phone = os.environ.get("GILANG_PHONE", "").replace("+", "").replace(" ", "").replace("-", "")
    bunga_phone = os.environ.get("BUNGA_PHONE", "").replace("+", "").replace(" ", "").replace("-", "")
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
        target_chat = f"{bunga_phone}@c.us" if bunga_phone else "bunga@c.us"
    else:
        target_chat = f"{gilang_phone}@c.us" if gilang_phone else "gilang@c.us"

    log.info("Dispatching reminder to %s: %s", target_chat, text)
    await client.send_message(chat_id=target_chat, text=text)


async def handle_proactive_scheduler_tick(client: WahaClient) -> None:
    """
    Evaluate pending tasks on each scheduler tick (every ~5 minutes):
    1. Stage 1 (Kickoff Buffer): Dispatched at (due - lead_time_minutes).
    2. Stage 2 (Final Cutoff / Due Alert): Dispatched at due time.
    3. Urgent 10-Minute Nag Loop: Nudges every 10m up to 60m + cross-partner alert at 30m.
    """
    log.info("Scheduler tick: Evaluating proactive reminders and nag loops...")
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
        if t.get("status") == "completed":
            continue

        title = t.get("title", "")
        due_str = t.get("due", "")
        assignee = str(t.get("assignee", "Gilang")).strip()
        priority = str(t.get("priority", "normal")).strip().lower()
        lead_mins = int(t.get("lead_time_minutes", 0) or 0)
        due_ts = parse_due_timestamp(due_str)

        if due_ts == float("inf"):
            # No parseable deadline, skip automated time-based triggers
            continue

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
            # Trigger if within lead buffer window and before actual due
            if now_ts >= (due_ts - lead_sec - 120) and now_ts < (due_ts - 120):
                lead_text = (
                    f"{lead_mins // 60} jam"
                    if (lead_mins >= 60 and lead_mins % 60 == 0)
                    else f"{lead_mins} menit"
                )
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
            # Must be past due and at least 9 minutes since last nudge
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
                    # 30-Minute Escalation + Partner Alert
                    msg_text = (
                        f"PENTING: {assignee}, tugas *{title}* sudah 30 menit lewat dari jadwal "
                        "dan belum ada konfirmasi."
                    )
                    await send_reminder_to_recipient(client, assignee, msg_text)

                    # Cross-partner alert to help wake up or check
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
                    # 60-Minute Stand Down Notice
                    msg_text = (
                        f"Helmis menghentikan pengingat otomatis untuk *{title}* (sudah 60 menit tanpa respon). "
                        "Tugas tetap tercatat 'pending' di daftar tugas."
                    )
                    await send_reminder_to_recipient(client, assignee, msg_text)
                    t["nudge_stopped"] = True
                    t["last_nudged_at"] = now_ts
                    log_activity(f"Urgent Nag stand-down reached (60m) for '{title}'")
                    updated_any = True

    if updated_any:
        save_memory(mem)
        log.info("Proactive evaluation completed and state saved to disk.")
    else:
        log.debug("No new reminders or nag pings triggered in this tick.")

