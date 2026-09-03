"""
intent.py — Typed intent/action planning for Helmis turns.

Builds a structured turn plan before the model is invoked: intent class,
domain, action type, entity selectors, declared side effects, destructive-scope
and ambiguity gates, and the authoritative source of truth for resolution.
Tool calling remains the execution mechanism; the plan only decides routing
and whether the model must be forced toward tools or asked to confirm first.
"""

import re
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Regex classification primitives (single source of truth; guardrails delegate)
# ---------------------------------------------------------------------------

QUERY_PATTERNS = re.compile(
    r"(?:"
    r"^(?:cek|check|lihat|liat|show|tampil(?:kan|in)?|list|daftar|cari(?:in|kan)?|search|find|baca(?:in|kan)?|read|rangkum|summarize)\b"
    r"|(?:ada\s+(?:tugas|jadwal|reminder|agenda|catatan|file)|apa\s+(?:aja|saja|jadwal|tugas|agenda|kegiatan))"
    r"|(?:tugas|task|reminder|jadwal|catatan|note|file|dokumen)\s+(?:apa|mana|yang\s+mana)"
    r"|(?:berapa|kapan|dimana|siapa|nomor|kontak|email)\b"
    r"|\?$"
    r")",
    re.IGNORECASE,
)

ACTION_PATTERNS = re.compile(
    r"(?:"
    # Reschedule / snooze / postpone relative phrases
    r"(?:\b(?:siangan|sorean|malaman|besokan|ntar|entar|nanti(?:\s+aja)?|tunda|mundur(?:in|kan)?|geser|pindah(?:in|kan)?)\b)"
    r"|(?:ganti|ubah|update|reschedule|snooze|postpone)\s+(?:jadwal|waktu|jam|deadline|reminder|tugas)"
    r"|\b(?:jam|pukul)\s+\d{1,2}(?:[:.]\d{2})?"
    # Create / add / record (e.g. ingetin gw bayar kosan, remind me, catat tugas)
    r"|(?:inget(?:in|kan)?|remind|catat(?:in|kan)?|jadwal(?:in|kan)?|bikin(?:in|kan)?|buat(?:in|kan)?|tambah(?:in|kan)?|set)\b"
    r"|(?:tolong|coba|minta)\s+(?:kirim|hapus|simpan|save|delete|send|forward)"
    # Delete / complete / mark
    r"|(?:hapus|delete|buang|hilang(?:in|kan)?)\s+(?:tugas|task|reminder|catatan|note|memori|file)"
    r"|(?:selesai(?:in|kan)?|done|complete|mark|tandai)\s+(?:tugas|task|reminder)"
    r"|(?:tugas|task|reminder)\s+.*?\s+(?:selesai|done|beres|kelar)"
    # File / vault operations
    r"|(?:kirim(?:in|kan)?|send|forward)\s+(?:file|dokumen|foto|gambar|pdf)"
    r"|(?:simpan|save)\s+(?:ini|file|dokumen|foto)"
    # Explicit time-shift directives
    r"|\b\d+\s*(?:jam|menit|minute|hour)\s+lagi\b"
    r")",
    re.IGNORECASE,
)

_MUTATING_VERB_PATTERN = re.compile(
    r"(?:"
    # Bare create/record verbs (old classifier treated these as action alone)
    r"\b(?:inget(?:in|kan)?|remind|catat(?:in|kan)?|jadwal(?:in|kan)?|bikin(?:in|kan)?|buat(?:in|kan)?|"
    r"tambah(?:in|kan)?|set|ubah|ganti|update|geser|tunda|mundur(?:in|kan)?|pindah(?:in|kan)?)\b"
    # Delete/complete/send verbs require an object noun to avoid false positives
    r"|(?:hapus|delete|buang|hilang(?:in|kan)?)\s+\S+"
    r"|(?:selesai(?:in|kan)?|done|complete|tandai|mark)\s+\S+"
    r"|(?:tolong|coba|minta)\s+(?:kirim|hapus|simpan|save|delete|send|forward)"
    r"|reconcile|clear\b)",
    re.IGNORECASE,
)

_DELETE_VERB_PATTERN = re.compile(
    r"\b(?:hapus|delete|buang|hilang(?:in|kan)?|reconcile|clear)\b", re.IGNORECASE
)

# Suffixed mutation forms that flip an otherwise query-shaped message
# (e.g. "jadwalkan rapat" is a create, "cek jadwal besok" is not).
_MUTATION_SUFFIX_PATTERN = re.compile(
    r"\b(?:ingetin|ingetkan|remind|catatin|catatkan|buatkan|bikinin|jadwalkan|hapus|delete|geser|mundurin|mundurkan)\b",
    re.IGNORECASE,
)

_CREATE_VERB_PATTERN = re.compile(
    r"\b(?:inget(?:in|kan)?|remind|catat(?:in|kan)?|jadwal(?:in|kan)?|bikin(?:in|kan)?|buat(?:in|kan)?|"
    r"tambah(?:in|kan)?|set)\b",
    re.IGNORECASE,
)

_UPDATE_VERB_PATTERN = re.compile(
    r"\b(?:ubah|ganti|update|geser|tunda|mundur(?:in|kan)?|pindah(?:in|kan)?|reschedule|snooze)\b",
    re.IGNORECASE,
)

_COMPLETE_VERB_PATTERN = re.compile(
    r"\b(?:selesai(?:in|kan)?|done|complete|tandai|mark|beres|kelar)\b", re.IGNORECASE
)

_SEND_VERB_PATTERN = re.compile(
    r"(?:kirim(?:in|kan)?|send|forward)\s+(?:file|dokumen|foto|gambar|pdf|pesan|chat|message|media|ini|itu)",
    re.IGNORECASE
)

_DOMAIN_PATTERNS: dict[str, re.Pattern[str]] = {
    "task": re.compile(r"\b(?:tugas|task|reminder|deadline|agenda)\b", re.IGNORECASE),
    "schedule": re.compile(r"\b(?:jadwal|schedule|kalender|calendar)\b", re.IGNORECASE),
    "note": re.compile(r"\b(?:catatan|note|notes)\b", re.IGNORECASE),
    "memory": re.compile(r"\b(?:memori|memory|ingatan|fakta|fact|preferensi|preference)\b", re.IGNORECASE),
    "person": re.compile(r"\b(?:kontak|contact|orang|person)\b", re.IGNORECASE),
    "vault": re.compile(r"\b(?:file|dokumen|document|foto|gambar|pdf|vault)\b", re.IGNORECASE),
    "whatsapp": re.compile(r"\b(?:chat|pesan|message|wa|whatsapp)\b", re.IGNORECASE),
    "web": re.compile(r"https?://|docs\.google|sheets\.google|drive\.google|\b(?:cari(?:in|kan)?|search)\b", re.IGNORECASE),
}

_BULK_SCOPE_PATTERN = re.compile(r"\b(?:semua|semua-nya|all|seluruh|bagai(?:mana)?\s+pun)\b", re.IGNORECASE)

_QUOTED_PATTERN = re.compile(r"[\"'\u201c\u2018]([^\"'\u201d\u2019]+)[\"'\u201d\u2019]")

SOURCE_OF_TRUTH = {
    "task": "task store records",
    "schedule": "schedule records",
    "note": "note records",
    "memory": "semantic memory claims",
    "person": "person records",
    "vault": "vault files",
    "whatsapp": "WhatsApp chat history",
    "web": "live web fetch",
    "unknown": "model's own context",
}

DESTRUCTIVE_ACTION_TYPES = {"delete"}


@dataclass
class TurnPlan:
    """Typed, inspectable plan for a single user turn."""

    intent: str  # action | query | chat
    domain: str  # task | schedule | note | memory | person | vault | whatsapp | web | unknown
    action_type: str  # create | update | delete | complete | send | fetch | none
    selectors: list[str] = field(default_factory=list)
    side_effects: list[str] = field(default_factory=list)
    destructive: bool = False
    requires_confirmation: bool = False
    confirmation_reason: str = ""
    source_of_truth: str = "model's own context"
    matches: list[dict[str, Any]] = field(default_factory=list)


def _detect_domain(text: str) -> str:
    for domain, pattern in _DOMAIN_PATTERNS.items():
        if pattern.search(text):
            return domain
    return "unknown"


def _effective_domain(text: str, action_type: str) -> str:
    """Resolve 'unknown' domains: bare create/complete verbs imply task/reminder."""
    domain = _detect_domain(text)
    if domain == "unknown" and action_type in ("create", "complete", "update", "delete"):
        return "task"
    return domain


def _detect_action_type(text: str) -> str:
    if _DELETE_VERB_PATTERN.search(text):
        return "delete"
    if _COMPLETE_VERB_PATTERN.search(text):
        return "complete"
    if _UPDATE_VERB_PATTERN.search(text):
        return "update"
    if _SEND_VERB_PATTERN.search(text):
        return "send"
    if _CREATE_VERB_PATTERN.search(text):
        return "create"
    return "none"


def _side_effects(action_type: str) -> list[str]:
    mapping = {
        "create": ["persist new record"],
        "update": ["mutate existing record"],
        "delete": ["remove existing record(s)"],
        "complete": ["mark record completed"],
        "send": ["outbound WhatsApp delivery"],
    }
    return list(mapping.get(action_type, []))


def classify_intent(plan: TurnPlan) -> str:
    """Map a typed plan to the coarse intent string ('action'/'query'/'chat')."""
    return plan.intent


def build_turn_plan(text: str) -> TurnPlan:
    """Classify a turn into a typed plan without mutating any state."""
    clean = (text or "").strip()
    if not clean:
        return TurnPlan(intent="chat", domain="unknown", action_type="none")

    raw_action_type = _detect_action_type(clean)
    domain = _effective_domain(clean, raw_action_type)

    if QUERY_PATTERNS.search(clean) and not _MUTATION_SUFFIX_PATTERN.search(clean):
        intent = "query"
    elif ACTION_PATTERNS.search(clean) or _MUTATING_VERB_PATTERN.search(clean):
        intent = "action"
    elif QUERY_PATTERNS.search(clean):
        intent = "query"
    elif domain == "web":
        intent = "query"
    else:
        intent = "chat"

    if intent == "action" and raw_action_type == "none":
        raw_action_type = "update"

    selectors = [m.strip() for m in _QUOTED_PATTERN.findall(clean)]
    destructive = intent == "action" and raw_action_type in DESTRUCTIVE_ACTION_TYPES
    if destructive and _BULK_SCOPE_PATTERN.search(clean):
        destructive = True

    plan = TurnPlan(
        intent=intent,
        domain=domain,
        action_type=raw_action_type if intent == "action" else "none",
        selectors=selectors,
        side_effects=_side_effects(raw_action_type) if intent == "action" else [],
        destructive=destructive,
        source_of_truth=SOURCE_OF_TRUTH.get(domain, SOURCE_OF_TRUTH["unknown"]),
    )

    if destructive:
        plan.requires_confirmation = True
        plan.confirmation_reason = "destructive_scope"
    return plan


def resolve_task_entities(plan: TurnPlan) -> TurnPlan:
    """Resolve quoted selectors against task records; set ambiguity gate.

    Tool-layer resolution stays authoritative; this pre-resolution only lets
    the plan ask for clarification before a model call instead of after a
    wrong mutation.
    """
    if plan.intent != "action" or plan.domain not in ("task", "unknown"):
        return plan
    if not plan.selectors:
        return plan

    from ..memory.store import get_repository, identity_key

    try:
        tasks = get_repository().list_tasks()
    except Exception:  # pragma: no cover - store unavailable degrades to no matches
        return plan

    matches: list[dict[str, Any]] = []
    for selector in plan.selectors:
        query = identity_key(selector)
        for task in tasks:
            title_key = identity_key(str(task.get("identity_key") or task.get("title", "")))
            if query == title_key or query in title_key:
                matches.append(
                    {"task_id": task.get("task_id"), "title": task.get("title"), "status": task.get("status")}
                )
    plan.matches = matches
    if len(matches) > 1:
        plan.requires_confirmation = True
        plan.confirmation_reason = "ambiguous_selector"
    return plan


def should_force_tools(plan: TurnPlan) -> bool:
    """Only unambiguous, non-destructive action plans get forced tool calling."""
    return plan.intent == "action" and not plan.requires_confirmation


def plan_system_directive(plan: TurnPlan) -> str:
    """Deterministic directive appended to the system instruction, or ''. """
    if plan.intent != "action":
        return ""
    lines = [
        "### TURN PLAN (deterministic routing)",
        f"- Domain: {plan.domain}. Source of truth: {plan.source_of_truth}.",
    ]
    if plan.side_effects:
        lines.append(f"- Declared side effects: {', '.join(plan.side_effects)}.")
    if plan.requires_confirmation:
        if plan.confirmation_reason == "destructive_scope":
            lines.append(
                "- DESTRUCTIVE SCOPE: Jangan langsung mengeksekusi hapus/bulk mutation. "
                "Konfirmasi dulu ke user: sebutkan scope persis yang akan terdampak, "
                "dan eksekusi hanya setelah user mengonfirmasi."
            )
        elif plan.confirmation_reason == "ambiguous_selector":
            option_list = ", ".join(
                f"'{m.get('title')}' ({m.get('task_id')})" for m in plan.matches
            )
            lines.append(
                "- AMBIGUOUS SELECTOR: Beberapa record cocok (" + option_list + "). "
                "Tanyakan ke user record mana yang dimaksud sebelum mutate. "
                "Jangan menebak."
            )
    return "\n".join(lines)
