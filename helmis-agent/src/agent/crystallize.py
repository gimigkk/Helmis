"""
crystallize.py — Autonomous Skill Crystallizer & Background Reflection Engine.

Implements the Voyager / Hermes Agent pattern:
After completing complex multi-tool workflows or novel procedural solutions,
an asynchronous background task reflects on the turn trajectory, extracts the
reusable procedure, and crystallizes it into a persistent SKILL.md playbook
under config/skills/.

Zero-Latency: Runs as a fire-and-forget background task after the response
has already been returned to the user via WhatsApp.
"""

import asyncio
import json
import logging
import re
from typing import Any

import httpx

from ..memory.store import log_activity
from .cascade import GEMINI_KEYS, get_next_gemini_key


log = logging.getLogger("helmis-crystallize")

# Tool categories considered trivial/read-only that don't warrant standalone skills
TRIVIAL_TOOLS = {
    "list_tasks",
    "list_notes",
    "list_skills",
    "list_vault_files",
    "recall_memory",
    "search_memory",
    "get_person",
    "load_skill",
}


def should_attempt_crystallization(
    executed_tools: list[dict[str, Any]],
    user_message: str,
) -> bool:
    """
    Fast pre-filter to determine if a turn warrants autonomous skill crystallization.
    Prevents skill pollution / bloat on casual or trivial turns.
    """
    if not executed_tools:
        return False

    successful_tools = [
        t for t in executed_tools if t.get("result", {}).get("status") == "success"
    ]
    if not successful_tools:
        return False

    tool_names = [t.get("name", "") for t in successful_tools]
    unique_non_trivial = [n for n in set(tool_names) if n not in TRIVIAL_TOOLS]

    # Trigger Condition 1: Multi-step pipeline (2+ distinct non-trivial tools)
    # e.g. read_vault_file + execute_code, or search_web + save_note + send_whatsapp_message
    if len(unique_non_trivial) >= 2:
        return True

    # Trigger Condition 2: Custom Python computation solved via execute_code
    if "execute_code" in tool_names:
        for t in successful_tools:
            if t.get("name") == "execute_code":
                code = str(t.get("args", {}).get("code", "")).strip()
                # If code is non-trivial (> 40 chars, involves math, parsing, date logic)
                if len(code) > 40:
                    return True

    # Trigger Condition 3: Explicit teaching language in user prompt
    teach_patterns = re.compile(
        r"(?:mulai sekarang|setiap kali|kalau ada|prosedurnya|caranya|aturan baru|formatnya|ingat cara)\b",
        re.IGNORECASE,
    )
    if teach_patterns.search(user_message):
        return True

    return False


async def auto_crystallize_turn(
    sender_name: str,
    user_message: str,
    executed_tools: list[dict[str, Any]],
    final_response: str,
) -> None:
    """
    Asynchronous reflection pass:
    Evaluates the completed turn trajectory and crystallizes a new SKILL.md if novel.
    """
    try:
        if not should_attempt_crystallization(executed_tools, user_message):
            return

        log.debug("Starting background auto-crystallization for [%s]...", sender_name)

        from ..tools.skills import handle_create_skill, list_available_skills

        existing_skills = list_available_skills()
        existing_names = [s.get("name", "") for s in existing_skills]


        # Summarize execution trajectory for the critic LLM
        trajectory_steps = []
        for i, t in enumerate(executed_tools, 1):
            name = t.get("name")
            args = t.get("args", {})
            res = t.get("result", {})
            status = res.get("status", "unknown")
            msg_snippet = str(res.get("message") or res.get("stdout") or res.get("error") or "")[:200]
            trajectory_steps.append(f"{i}. Tool `{name}` (status: {status})\n   Args: {json.dumps(args, ensure_ascii=False)}\n   Output: {msg_snippet}")

        trajectory_text = "\n".join(trajectory_steps)

        critic_prompt = f"""You are the Procedural Memory & Skill Crystallizer for Helmis (personal AI secretary for Gilang and Bunga).

Evaluate this completed turn trajectory to determine if a novel, reusable operational procedure, multi-step tool workflow, or SOP was discovered that should be crystallized into a persistent SKILL.md playbook.

### USER REQUEST:
"{user_message}"

### TOOLS EXECUTED IN THIS TURN:
{trajectory_text}

### FINAL VERIFIED RESPONSE:
"{final_response}"

### EXISTING SKILLS IN SYSTEM:
{json.dumps(existing_names)}

### CRITERIA FOR CRYSTALLIZATION:
1. ONLY crystallize if the workflow is reusable for FUTURE similar tasks (e.g. specialized data format parsing, custom formula calculation, multi-step report generation, couple coordination workflow).
2. DO NOT crystallize one-off trivial queries (e.g. checking one task, reading one note, simple banter).
3. DO NOT duplicate an existing skill already in the system.
4. Output MUST be valid JSON strictly matching the schema below.

```json
{{
  "crystallize": true or false,
  "reason": "Brief explanation of why this is or isn't a reusable skill",
  "skill_name": "auto-kebab-case-name",
  "description": "One sentence description of when to use this skill",
  "content": "Full markdown playbook with YAML header, operational directives, tool sequences, and rules adhering to agentskills.io format"
}}
```"""

        payload = {
            "contents": [{"role": "user", "parts": [{"text": critic_prompt}]}],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 1024,
                "responseMimeType": "application/json",
            },
        }

        if not GEMINI_KEYS:
            return

        api_key = get_next_gemini_key()
        # Use fast lite model for background crystallization
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:generateContent?key={api_key}"

        async with httpx.AsyncClient(timeout=10.0) as http_client:
            resp = await http_client.post(url, json=payload)
            if resp.status_code != 200:
                log.debug("Crystallization LLM call returned %d: %s", resp.status_code, resp.text[:200])
                return

            data = resp.json()
            candidates = data.get("candidates", [])
            if not candidates:
                return

            raw_json = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            if not raw_json:
                return

            decision = json.loads(raw_json)
            if not decision.get("crystallize"):
                log.debug("Auto-crystallization skipped by critic: %s", decision.get("reason", "Not reusable"))
                return

            skill_name = str(decision.get("skill_name", "")).strip().lower().replace(" ", "-")
            if not skill_name.startswith("auto-"):
                skill_name = f"auto-{skill_name}"
            # Clean safe characters
            skill_name = re.sub(r"[^a-z0-9\-]", "", skill_name)

            desc = str(decision.get("description", "Autonomously crystallized operational skill."))
            content = str(decision.get("content", "")).strip()

            if skill_name and content:
                res = await handle_create_skill(
                    args={"name": skill_name, "description": desc, "content": content},
                    default_sender="Helmis-AutoCrystallizer",
                )
                if res.get("status") == "success":
                    log.info(
                        "✨ [Autonomous Auto-Crystallization] Successfully synthesized new skill '%s': %s",
                        skill_name,
                        desc,
                    )
                    log_activity(f"Auto-crystallized new procedural skill: {skill_name}")

    except Exception as e:
        log.warning("Auto-crystallization background task encountered an error: %s", e)
