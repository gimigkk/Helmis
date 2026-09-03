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
import time
import uuid
from datetime import datetime
from datetime import datetime as DateTime
from typing import Any
from zoneinfo import ZoneInfo

from ..memory.recurrence import format_occurrence, next_occurrence_for_task
from ..memory.store import (
    fetch_tickable_tasks,
    get_repository,
    log_activity,
    parse_due_timestamp,
    update_task_fields,
)
from ..tools.registry import TOOL_REGISTRY, execute_tool_call
from ..tools.schema import GEMINI_TOOLS
from ..whatsapp.client import WahaClient
from .delivery import deliver_outbox_batch

log = logging.getLogger("helmis-proactive")
TZ = ZoneInfo("Asia/Jakarta")
OCCURRENCE_LEASE_SECONDS = 300.0

# Scheduled jobs may only execute tools that are both registered and declared
# in the model-facing schema; anything else is quarantined, never guessed.
_ALLOWED_JOB_KINDS = {"tool", "agent", "message"}


def _declared_tool_names() -> set[str]:
    names: set[str] = set()
    for declaration in GEMINI_TOOLS[0]["function_declarations"]:
        name = declaration.get("name")
        if isinstance(name, str):
            names.add(name)
    return names


def _quarantine_job(task: dict[str, Any], reason: str) -> bool:
    """Mark a malformed or unknown scheduled job quarantined (durable, no send)."""
    task["status"] = "quarantined"
    task["execution_status"] = "quarantined"
    task["error_message"] = reason
    task["completed_at"] = datetime.now(TZ).strftime("%Y-%m-%d %H:%M")
    log.error("Quarantined scheduled job for task %s: %s", task.get("task_id"), reason)
    log_activity(f"Scheduled job quarantined: {reason}")
    return False


def _occurrence_id(task_id: str, scheduled_for: float, stage: str = "default") -> str:
    """Derive a stable occurrence ID so repeated scheduler ticks are harmless."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"helmis:occurrence:{task_id}:{stage}:{scheduled_for:.6f}"))


def _reminder_occurrence_id(task_id: str, scheduled_for: float, stage: str) -> str:
    return _occurrence_id(task_id, scheduled_for, stage)


def _claim_task_occurrence(task: dict[str, Any], now_ts: float) -> tuple[dict[str, Any] | None, str | None]:
    """Materialize and claim the task's due occurrence for one scheduler worker."""
    due_ts = parse_due_timestamp(str(task.get("due", "")))
    task_id = str(task.get("task_id") or "")
    if not task_id or due_ts == float("inf"):
        return None, None
    repository = get_repository()
    occurrence = repository.ensure_occurrence(
        task_id, due_ts, _occurrence_id(task_id, due_ts), now_ts
    )
    claim_token = str(uuid.uuid4())
    claimed = repository.claim_occurrence(
        str(occurrence.get("occurrence_id", "")),
        now_ts,
        OCCURRENCE_LEASE_SECONDS,
        claim_token,
    )
    return claimed, claim_token if claimed else None


def _advance_recurrence(task: dict[str, Any], scheduled_for: float) -> dict[str, Any]:
    """Return the next due time for a recurring task, if one exists."""
    recurrence = task.get("recurrence") or task.get("recurrence_policy")
    if not isinstance(recurrence, dict):
        return {}
    scheduled_at = DateTime.fromtimestamp(scheduled_for, tz=TZ)
    next_due = next_occurrence_for_task(task, scheduled_at)
    if next_due is None:
        return {}
    return {"due": format_occurrence(next_due), "recurrence": recurrence, "recurrence_policy": recurrence}


async def _delayed_action_runner(task_id: str, delay_sec: float, client: WahaClient) -> None:
    """In-process high-precision countdown timer for near-horizon scheduled actions (<10 mins)."""
    try:
        log.info("Near-horizon countdown started for '%s' (delay: %.1fs)", task_id, delay_sec)
        await asyncio.sleep(delay_sec)
        tasks = get_repository().fetch_tickable_tasks()
        t = next((x for x in tasks if x.get("task_id") == task_id), None)
        # Accept the old title argument for existing callers; scheduler-created
        # timers always pass the stable task ID above.
        if t is None:
            t = next((x for x in tasks if x.get("title") == task_id), None)
        if t and str(t.get("status", "pending")).lower() == "pending":
            now_dt = datetime.now(TZ)
            now_str = now_dt.strftime("%A, %d %B %Y - %H:%M WIB")
            dispatched = await dispatch_scheduled_action(client=client, task=t, now_str=now_str)
            if dispatched:
                _persist_scheduler_task(t)
                log.info("Near-horizon timer successfully executed and saved for '%s'", task_id)
    except Exception as e:
        log.error("Error in near-horizon timer for '%s': %s", task_id, e)


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
            loop.create_task(_delayed_action_runner(str(task.get("task_id", "")), delay_sec, client))
            log.info("Spawned exact-second timer for '%s' (in %.1f seconds)", task.get("task_id"), delay_sec)
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


_MULTI_RECIPIENT_TOKENS = ("both", "semua", "shared", "trio", "group", "grup")


def _resolve_recipient_chat(assignee: str, *, cross_alert_recipient: str = "") -> str:
    """Resolve a recipient chat from data: people directory, or group JID for multi-recipient tokens."""
    from ..memory.store import get_person

    name = (cross_alert_recipient or assignee).strip()
    lowered = name.lower()

    if any(token in lowered for token in _MULTI_RECIPIENT_TOKENS):
        return os.environ.get("TRIO_GROUP_JID", "").strip()

    person = get_person(name) if name else None
    if person and person.get("phone"):
        return normalize_chat_target(str(person["phone"]))
    return ""


def _resolve_reminder_policy(task: dict[str, Any]) -> dict[str, Any] | None:
    """Resolve the nag policy for a task from data, falling back to task fields.

    Lookup order: reminder_policies row for this task, then task-level
    nag fields, then the urgent-priority default ladder (10m interval,
    5 nags, stand-down at 60m) expressed as plain data.
    Returns None when no nagging applies.
    """
    task_id = str(task.get("task_id") or "")
    if task_id:
        policies = get_repository().list_reminder_policies(task_id=task_id)
        if policies:
            return policies[0]

    raw_nag_policy = task.get("nag_policy")
    nag_policy: dict[str, Any] = raw_nag_policy if isinstance(raw_nag_policy, dict) else {}
    priority = str(task.get("priority", "normal")).strip().lower()
    nag_enabled = bool(task.get("nag_enabled")) or priority == "urgent"
    interval = task.get("nag_interval_minutes") or nag_policy.get("interval_minutes")
    max_nags = task.get("max_nags", nag_policy.get("max_nags"))
    if not nag_enabled:
        return None

    return {
        "policy_id": "derived",
        "task_id": task_id,
        "repeat_interval_minutes": max(1, int(interval)) if interval else 10,
        # max_nags counts the due reminder itself; max_repeats budgets extra nags.
        "max_repeats": max(0, int(max_nags) - 1) if max_nags is not None else 5,
        "acknowledgment_required": True,
        "stand_down_after_minutes": int(
            nag_policy.get("stand_down_after_minutes")
            or ((int(interval) if interval else 10) * (int(max_nags) if max_nags is not None else 6) + 10)
        ),
        "cross_alert_recipient": str(nag_policy.get("cross_alert_recipient", "") or ""),
    }


async def send_reminder_to_recipient(
    client: WahaClient,
    assignee: str,
    text: str,
    is_cross_alert: bool = False,
    task_id: str = "",
    stage: str = "reminder",
    scheduled_for: float | None = None,
    occurrence_id: str | None = None,
    claim_occurrence: bool = True,
) -> None:
    """Route human reminder text to the recipient resolved from data (directory/group)."""
    target_chat = _resolve_recipient_chat(assignee)
    if not target_chat:
        raise RuntimeError(f"No resolvable recipient for reminder assignee '{assignee}'")

    log.info("Dispatching reminder to %s: %s", target_chat, text)
    repository = get_repository()
    claim_token: str | None = None
    if task_id and scheduled_for is not None:
        occurrence_id = occurrence_id or _reminder_occurrence_id(task_id, scheduled_for, stage)
        occurrence = repository.ensure_occurrence(
            task_id, scheduled_for, occurrence_id, time.time(), stage=stage
        )
        if claim_occurrence:
            claim_token = str(uuid.uuid4())
            claimed = repository.claim_occurrence(
                str(occurrence["occurrence_id"]), time.time(), OCCURRENCE_LEASE_SECONDS, claim_token
            )
            if claimed is None:
                return
    idempotency_key = f"reminder:{task_id or 'unscheduled'}:{stage}:{target_chat}"
    queued = repository.enqueue_outbox(
        outbox_id=f"outbox-{abs(hash(idempotency_key))}",
        idempotency_key=idempotency_key,
        target_chat=target_chat,
        payload={"text": text},
        created_at=time.time(),
        occurrence_id=occurrence_id,
    )
    if queued.get("state") == "delivered":
        if claim_token and occurrence_id:
            repository.complete_occurrence(occurrence_id, claim_token)
        return
    result = await deliver_outbox_batch(client, outbox_id=str(queued["outbox_id"]))
    if result["delivered"] != 1:
        if claim_token and occurrence_id:
            repository.release_occurrence(occurrence_id, claim_token)
        raise RuntimeError(f"Reminder delivery failed for {target_chat}")
    if claim_token and occurrence_id:
        repository.complete_occurrence(occurrence_id, claim_token)


async def dispatch_scheduled_action(
    client: WahaClient,
    task: dict[str, Any],
    now_str: str,
    is_overdue_catchup: bool = False,
) -> bool:
    """
    Polymorphic executor for scheduled bot actions (Helmis tasks):
    1. ToolJobExecutor: Calls any registered, schema-declared tool.
    2. AgentLoopJobExecutor: Runs autonomous ReAct reasoning turn for dynamic tasks.
    3. Message fallback: extracts text from the title (plain scheduled message).

    Malformed or unknown jobs are quarantined, never silently reinterpreted.
    """
    title = task.get("title", "")
    job = task.get("job") or {}
    kind = str(job.get("kind", "")).strip().lower()
    tool_name = str(job.get("tool_name") or job.get("name") or "").strip()
    tool_args = job.get("tool_args") or job.get("args") or {}

    if job and kind and kind not in _ALLOWED_JOB_KINDS:
        return _quarantine_job(task, f"Unknown scheduled job kind '{kind}'")
    if job and kind == "message":
        # 'message' jobs must carry text explicitly; no title-sniffing reinterpretation.
        text_to_send = str(job.get("text") or "").strip()
        if not text_to_send:
            return _quarantine_job(task, "Scheduled 'message' job has no text")

    log.info("Executing scheduled action '%s' (kind: %s, tool: %s)...", title, kind, tool_name)
    task["execution_status"] = "running"

    try:
        # -------------------------------------------------------------------------
        # Strategy 1: Dynamic Tool Invocation via universal TOOL_REGISTRY
        # -------------------------------------------------------------------------
        if kind == "tool" or tool_name:
            if not tool_name:
                tool_name = "send_whatsapp_message"
            if tool_name not in TOOL_REGISTRY or tool_name not in _declared_tool_names():
                return _quarantine_job(
                    task, f"Scheduled job references unregistered/undeclared tool '{tool_name}'"
                )

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
            target_chat = job.get("target_chat") or job.get("chat_id") or ""
            if not target_chat:
                target_chat = _resolve_recipient_chat(str(task.get("requester") or "Gilang"))
            if not target_chat:
                return _quarantine_job(task, "Agent job has no resolvable target chat")

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
        # Strategy 3: Scheduled message (text from title extraction or job text)
        # -------------------------------------------------------------------------
        else:
            text_to_send = str(job.get("text") or "").strip() if job else ""
            if not text_to_send:
                quotes = re.findall(r'"([^"]*)"', title)
                if quotes:
                    text_to_send = quotes[0]
                elif ":" in title:
                    text_to_send = title.split(":", 1)[1].strip()
                else:
                    text_to_send = title

            target_chat = _resolve_recipient_chat(str(task.get("requester") or "Gilang"))
            if not target_chat:
                return _quarantine_job(task, "Scheduled message has no resolvable recipient")
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
    tasks = fetch_tickable_tasks()
    if not tasks:
        log.debug("No tasks in memory to evaluate.")
        return

    now_dt = datetime.now(TZ)
    now_ts = now_dt.timestamp()
    now_str = now_dt.strftime("%A, %d %B %Y - %H:%M WIB")

    for t in tasks:
        before_task = dict(t)
        try:
            status = str(t.get("status", "pending")).lower()
            if status in ("completed", "failed", "expired"):
                continue

            title = t.get("title", "")
            due_str = t.get("due", "")
            assignee = str(t.get("assignee", "Gilang")).strip()
            task_type = str(t.get("task_type", "reminder")).strip().lower()
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
                    next_fields = _advance_recurrence(t, due_ts)
                    if next_fields:
                        # Skip the missed occurrence but keep the recurrence alive:
                        # the series survives downtime and lands on its next slot.
                        t["status"] = "pending"
                        t["execution_status"] = "skipped_overdue"
                        t.update(next_fields)
                        t["due_reminded"] = False
                        t["reminded"] = False
                        t["nudge_count"] = 0
                        t["nudge_stopped"] = False
                        log.warning("Recurring action '%s' overdue >2h; skipped occurrence, advanced to %s", title, next_fields.get("due"))
                        log_activity(f"Recurring action skipped overdue occurrence: '{title}'")
                    else:
                        t["status"] = "expired"
                        t["execution_status"] = "expired"
                        t["completed_at"] = now_str
                        log.warning("Scheduled action '%s' was overdue by >2h. Marked expired.", title)
                        log_activity(f"Scheduled action expired (>2h): '{title}'")
                    continue

                # 2. Trigger Window: within 2 minutes of due or slightly overdue (<2h)
                if now_ts >= (due_ts - 120):
                    occurrence, claim_token = _claim_task_occurrence(t, now_ts)
                    if occurrence is None or claim_token is None:
                        continue
                    is_late = (now_ts - due_ts) > 300  # More than 5 mins late
                    dispatched = await dispatch_scheduled_action(
                        client=client,
                        task=t,
                        now_str=now_str,
                        is_overdue_catchup=is_late,
                    )
                    if dispatched:
                        if str(t.get("status", "pending")).lower() == "completed":
                            next_fields = _advance_recurrence(t, float(occurrence["scheduled_for"]))
                            if next_fields:
                                t["status"] = "pending"
                                t.update(next_fields)
                            get_repository().complete_occurrence(
                                str(occurrence["occurrence_id"]), claim_token
                            )
                        else:
                            get_repository().release_occurrence(
                                str(occurrence["occurrence_id"]), claim_token
                            )
                    continue

                # Not due yet, skip remainder of human reminder logic
                continue

            # =========================================================================
            # SECTION B: HUMAN TASKS & REMINDERS
            # =========================================================================
            kickoff_reminded = bool(t.get("kickoff_reminded"))
            due_reminded = bool(t.get("due_reminded") or t.get("reminded"))
            nudge_count = int(t.get("nudge_count", 0))
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
                    await send_reminder_to_recipient(
                        client, assignee, msg_text, task_id=str(t.get("task_id", "")), stage="kickoff",
                        scheduled_for=due_ts,
                    )
                    t["kickoff_reminded"] = True
                    t["kickoff_reminded_at"] = now_str
                    log_activity(f"Stage 1 kickoff sent to {assignee} for '{title}' (Lead: {lead_text})")
                    continue

            # ---------------------------------------------------------------------
            # 2. STAGE 2: Final Deadline Alert
            # ---------------------------------------------------------------------
            if not due_reminded:
                # Safeguard: If task is already > 2 hours overdue when first loaded, skip
                # the stale occurrence but keep recurring series alive via advancement.
                if (now_ts - due_ts) > 7200:
                    next_fields = _advance_recurrence(t, due_ts)
                    if next_fields:
                        t.update(next_fields)
                        t["due_reminded"] = False
                        t["reminded"] = False
                        t["nudge_count"] = 0
                        t["nudge_stopped"] = False
                        log.info("Recurring reminder '%s' overdue >2h; skipped occurrence, advanced to %s", title, next_fields.get("due"))
                        continue
                    t["due_reminded"] = True
                    t["reminded"] = True
                    t["reminded_at"] = now_str
                    t["nudge_stopped"] = True
                    log.info("Task '%s' was already >2h overdue. Silently marked reminded to avoid false alarms.", title)
                    continue

                # Trigger if within 5 minutes of due or overdue within recent window
                if now_ts >= (due_ts - 300):
                    msg_text = (
                        f"Halo {assignee}, pengingat deadline: *{title}* ({due_str}). "
                        "Jika sudah selesai, kabari Helmis ya."
                    )
                    await send_reminder_to_recipient(
                        client, assignee, msg_text, task_id=str(t.get("task_id", "")), stage="due",
                        scheduled_for=due_ts,
                    )
                    t["due_reminded"] = True
                    t["reminded"] = True
                    t["reminded_at"] = now_str
                    t["first_reminded_at"] = now_ts
                    t["last_nudged_at"] = now_ts
                    t["nudge_count"] = 1
                    log_activity(f"Stage 2 due reminder sent to {assignee} for '{title}'")
                    # Recurring human reminders must also advance, otherwise the
                    # series dies after its first delivered due reminder.
                    next_fields = _advance_recurrence(t, due_ts)
                    if next_fields:
                        t.update(next_fields)
                        t["due_reminded"] = False
                        t["reminded"] = False
                        t["kickoff_reminded"] = False
                        t["nudge_count"] = 0
                        t["nudge_stopped"] = False
                        t["last_nudged_at"] = None
                    continue

            # ---------------------------------------------------------------------
            # 3. POLICY-DRIVEN NAG ESCALATION LOOP
            # Cadence, repeat budget, stand-down, and cross-alert all come from
            # the resolved reminder policy (repository row, task fields, or the
            # urgent default). No per-person or per-count Python branches.
            # ---------------------------------------------------------------------
            policy = _resolve_reminder_policy(t)
            if policy and due_reminded and not nudge_stopped:
                interval_min = max(1, int(policy.get("repeat_interval_minutes") or 10))
                max_repeats = max(0, int(policy.get("max_repeats") or 0))
                last_nudged = float(t.get("last_nudged_at") or 0)
                time_since_nudge = (now_ts - last_nudged) if last_nudged else (now_ts - due_ts)
                if time_since_nudge >= interval_min * 60 * 0.9:
                    next_count = nudge_count + 1
                    if next_count > max_repeats + 1:
                        stand_down = int(policy.get("stand_down_after_minutes") or 0)
                        stood_down_min = stand_down if stand_down else interval_min * (max_repeats + 1)
                        msg_text = (
                            f"Helmis menghentikan pengingat otomatis untuk *{title}* "
                            f"(sudah {stood_down_min} menit tanpa respon). "
                            "Tugas tetap tercatat 'pending' di daftar target."
                        )
                        await send_reminder_to_recipient(
                            client, assignee, msg_text, task_id=str(t.get("task_id", "")), stage="stand-down",
                            scheduled_for=due_ts,
                        )
                        t["nudge_stopped"] = True
                        t["last_nudged_at"] = now_ts
                        log_activity(f"Reminder stand-down reached ({stood_down_min}m) for '{title}'")
                    else:
                        minutes_overdue = int((now_ts - due_ts) // 60)
                        cross_recipient = str(policy.get("cross_alert_recipient") or "")
                        msg_text = (
                            f"PENTING: {assignee}, pengingat ke-{next_count} untuk *{title}* "
                            f"({minutes_overdue} menit lewat). Mohon konfirmasi statusnya ya."
                        )
                        await send_reminder_to_recipient(
                            client, assignee, msg_text, task_id=str(t.get("task_id", "")), stage=f"nag-{next_count}",
                            scheduled_for=due_ts,
                        )
                        # Cross-alert at the midpoint of the nag budget.
                        if cross_recipient and max_repeats >= 2 and next_count == 2 + (max_repeats - 1) // 2:
                            cross_msg = (
                                f"PENTING: {cross_recipient}, {assignee} belum ada konfirmasi untuk tugas "
                                f"urgent *{title}* ({minutes_overdue} menit lewat). Tolong bantu cek ya."
                            )
                            await send_reminder_to_recipient(
                                client, cross_recipient, cross_msg, is_cross_alert=True,
                                task_id=str(t.get("task_id", "")), stage=f"nag-{next_count}-cross-alert",
                                scheduled_for=due_ts,
                            )
                        t["nudge_count"] = next_count
                        t["last_nudged_at"] = now_ts
                        log_activity(f"Policy nag #{next_count} sent to {assignee} for '{title}'")

        except Exception as task_err:
            log.error("Error evaluating proactive reminder for task '%s': %s", t.get("title"), task_err)

        finally:
            _persist_scheduler_task(t, before_task)

    log.info("Proactive evaluation completed with repository-backed task updates.")


def _persist_scheduler_task(
    task: dict[str, Any], before: dict[str, Any] | None = None
) -> None:
    """Persist only scheduler changes using the task's stable ID and version."""
    task_id = str(task.get("task_id") or "")
    if not task_id:
        return
    previous = before or {}
    fields = {
        key: value
        for key, value in task.items()
        if key not in {"task_id", "version"} and value != previous.get(key)
    }
    if not fields:
        return
    result = update_task_fields(
        task_id, fields, expected_version=int(previous.get("version", task.get("version", 1)))
    )
    if result.get("outcome") == "conflict":
        log.info("Skipped stale scheduler update for task %s", task_id)
