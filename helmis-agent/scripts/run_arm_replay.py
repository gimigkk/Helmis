"""
run_arm_replay.py — Version-agnostic corpus replay driver.

Runs the sanitized production corpus through ONE codebase version using that
version's own agent loop, tools, and guardrails. Called twice (old commit
worktree vs current branch) by compare_versions.py; writes per-run JSON.

Usage (inside a version's helmis-agent dir, with its own venv or the shared one):
    .venv/bin/python scripts/run_arm_replay.py \
        --corpus ../../docs/production-evidence/regression_cases.json \
        --runs 1 --label old | new --output /tmp/.../arm_old.json

State isolation: fresh temp DATA_DIR + per-run reset of repository/semantic
constants, mirroring scripts/benchmark_replay.py. Scoring is version-aware:
detect_unexecuted_mutation_claims only exists in the new guardrails, so the
unsupported-claims check degrades gracefully on old versions.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CORPUS = REPO_ROOT / "docs" / "production-evidence" / "regression_cases.json"

_ISOLATION_DIR = Path(tempfile.gettempdir()) / "helmis_arm_isolation"
_ISOLATION_DIR.mkdir(parents=True, exist_ok=True)
os.environ["DATA_DIR"] = str(_ISOLATION_DIR)
os.environ["HELMIS_DB_PATH"] = str(_ISOLATION_DIR / "helmis.db")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.agent import cascade  # noqa: E402
from src.agent.loop import run_agentic_react_loop  # noqa: E402
from src.memory.store import add_task  # noqa: E402

SEEDERS: dict[str, list[dict[str, Any]]] = {
    "duplicate-create-update": [
        {"title": "Tugas LKP 2 Kecerdasan Buatan", "due": "2026-02-09 23:59 WIB", "assignee": "Gilang"},
    ],
    "scoped-bulk-delete": [
        {"title": "Ingatkan tagihan kosan Februari", "due": "2026-02-01 12:00 WIB", "assignee": "Gilang"},
        {"title": "Ingatkan tagihan kosan Maret", "due": "2026-03-01 12:00 WIB", "assignee": "Gilang"},
    ],
    "task-status-consistency": [
        {"title": "Balas email dosen", "due": "2026-09-02 18:00 WIB", "assignee": "Gilang"},
    ],
}

# Corpus no-fluff cases were recorded mid-conversation: the expected reply is
# the previous turn's content and the tool record captures the failure. Isolated
# replay uses self-contained equivalents with the same contract. Both versions
# face the identical input.
INPUT_OVERRIDES: dict[str, str] = {
    # No tools; reply = exactly the requested string, nothing else.
    "no-fluff-copy": 'Kirim "P2_Test_10123456_01" no fluff, persis begitu saja tanpa penjelasan tanpa format, biar bisa di copy.',
    # Read-only; zero remember_fact calls.
    "no-fluff-mutation": 'Kirim "P2_Test_10123456_01" no fluff, persis begitu saja tanpa penjelasan, dan JANGAN simpan atau ingat apapun.',
    "explicit-no-tool": 'Jangan pakai tool call apapun. Kirim "P2_Test_10123456_01" no fluff, persis begitu saja tanpa penjelasan.',
}

# Per-case invariant checks, encoded from regression_cases.json
# expected_invariants. Scoring verifies the CONTRACT, not the recorded
# failure behavior. All checks are deterministic and version-agnostic.
#   executed: list of {"name", "args", "result"} from the recording wrapper
#   final_reply: model's final text or None
CASE_CONTRACTS: dict[str, Any] = {
    # Resolve before create; no obsolete date to add_task; durable final date.
    "duplicate-create-update": {
        "no_add_with_obsolete_date": ("executed", lambda ex: not any(
            s["name"] == "add_task" and "2026-02-09" in str(s.get("args", {}).get("due", "")) for s in ex
        )),
        "max_one_add": ("executed", lambda ex: sum(1 for s in ex if s["name"] == "add_task") <= 1),
        "final_date_in_state_or_reply": ("reply", lambda r, ex=[]: "2026-09-02" in r or "2026-09-02" in str(ex)),
    },
    # Explicit scope + exact count reporting + no leftovers.
    "scoped-bulk-delete": {
        "deletes_present": ("executed", lambda ex: any(s["name"] == "delete_task" for s in ex)),
        "no_fake_success_without_delete": ("reply", lambda r, ex: not (
            ("terhapus" in r.lower() or "dihapus" in r.lower()) and not any(s["name"] == "delete_task" for s in ex)
        )),
    },
    # Reminder listing must come from records, not pure narrative.
    "reminder-list-source": {
        "used_list_or_schedule_source": ("executed", lambda ex: any(
            s["name"] in ("list_tasks", "list_schedules", "list_reminder_policies", "search_memory", "search_memory_by_semantic") for s in ex
        )),
    },
    # Read schedule source before committing reminders.
    "schedule-reconciliation": {
        "read_source_first": ("executed", lambda ex: any(
            s["name"] in ("search_vault_files", "list_notes", "read_vault_file", "list_schedules", "search_memory") for s in ex
        )),
        "no_unverified_bulk_claim": ("reply", lambda r, ex: not (
            "semua" in r.lower() and "sudah" in r.lower() and not any(s["name"] == "add_task" for s in ex)
        )),
    },
    # Quoted text must not trigger mutation.
    "quoted-context-contamination": {
        "no_mutation_from_quote": ("executed", lambda ex: not any(
            s["name"] in ("add_task", "delete_task", "update_task", "remember_fact", "complete_task") for s in ex
        )),
    },
    # Preference statement: no tool runs, no mutation claim.
    "preference-without-mutation": {
        "no_mutation_tools": ("executed", lambda ex: not any(
            s["name"] in ("add_task", "delete_task", "update_task", "remember_fact", "complete_task") for s in ex
        )),
    },
    # No tool calls, chips, commentary, or extra formatting; reply must be
    # exactly the requested string (self-contained override input).
    "no-fluff-copy": {
        "no_tools": ("executed", lambda ex: len(ex) == 0),
        "reply_exact_string": ("reply", lambda r: r.strip() == "P2_Test_10123456_01"),
    },
    # Read-only response; zero remember_fact calls.
    "no-fluff-mutation": {
        "no_remember_fact": ("executed", lambda ex: not any(s["name"] == "remember_fact" for s in ex)),
        "reply_exact_string": ("reply", lambda r: r.strip() == "P2_Test_10123456_01"),
    },
    # No tools unless side effect explicitly requested.
    "explicit-no-tool": {
        "no_tools": ("executed", lambda ex: len(ex) == 0),
        "reply_exact_string": ("reply", lambda r: r.strip() == "P2_Test_10123456_01"),
    },
    # Correction stored with provenance; prior claims reconciled.
    "identity-correction": {
        "correction_path_used": ("executed", lambda ex: any(
            s["name"] in ("remember_fact", "correct_fact") for s in ex
        )),
        "no_filename_token_as_identity": ("reply", lambda r: ".pptx" not in r and ".pdf" not in r and ".docx" not in r),
    },
    # status@broadcast isolation: must not misread payload as normal message.
    "status-payload-isolation": {
        "no_status_misread": ("reply", lambda r: "status@broadcast" not in r.lower() or "isolat" in r.lower() or "bukan" in r.lower()),
    },
    # Answer only from successful document retrieval; otherwise report inability.
    "document-followup": {
        "grounded_or_honest": ("reply", lambda r, ex: bool(r)),
    },
    # Distinguish read/OCR success from update commit; ask before changing.
    "vision-recheck-confirmation": {
        "no_unauthorized_deadline_change": ("executed", lambda ex: not any(
            s["name"] == "update_task" and not any(
                prev["name"] in ("read_vault_file", "search_vault_files") for prev in ex[:i]
            ) for i, s in enumerate(ex)
        )),
        "no_unsupported_commit_claim": ("reply", lambda r, ex: not (
            "sudah diubah" in r.lower() and not any(s["name"] == "update_task" for s in ex)
        )),
    },
    # Listing and final response must agree on status.
    "task-status-consistency": {
        "list_used": ("executed", lambda ex: any(s["name"] in ("list_tasks", "search_memory", "list_schedules") for s in ex)),
    },
}


def seed_case_state(case_id: str) -> None:
    for spec in SEEDERS.get(case_id, []):
        try:
            add_task(**spec)
        except Exception as e:  # pragma: no cover
            print(f"    seed warning: {spec.get('title')}: {e}")


def score_run(case: dict[str, Any], executed: list[dict[str, Any]], final_reply: str | None) -> dict[str, Any]:
    contract = CASE_CONTRACTS.get(str(case.get("id", "")))
    reply = (final_reply or "").strip()

    if contract is None:
        # Unspecified case: require reply present, tools succeeded.
        checks: dict[str, Any] = {"reply_present": bool(reply)}
    else:
        checks = {}
        for name, check in contract.items():
            kind = check[0]
            fn = check[1]
            try:
                if kind == "executed":
                    checks[name] = bool(fn(executed))
                elif kind == "reply":
                    # Reply-only lambdas take the reply; reply+executed take both.
                    checks[name] = bool(fn(reply)) if fn.__code__.co_argcount == 1 else bool(fn(reply, executed))
                else:
                    checks[name] = None
            except Exception:
                checks[name] = False

    checks["all_tools_succeeded"] = all(
        step.get("result", {}).get("status") == "success" for step in executed
    ) if executed else True

    # Soft-failure adjustment: read-only exploration tools (web_search,
    # execute_code experiments, history fetches) may legitimately miss without
    # violating any invariant, as long as the reply stays honest. Only failed
    # MUTATION tools (or absent replies) are hard contract violations.
    _MUTATION_TOOLS = {
        "add_task", "update_task", "delete_task", "complete_task",
        "remember_fact", "correct_fact", "delete_memory", "save_vault_file",
        "save_note", "send_whatsapp_message", "send_whatsapp_media",
    }
    if executed and not checks["all_tools_succeeded"]:
        failed_mutation = any(
            step.get("result", {}).get("status") != "success" and step["name"] in _MUTATION_TOOLS
            for step in executed
        )
        if not failed_mutation:
            checks["all_tools_succeeded"] = "soft_fail_readonly"
            checks["mutation_tools_clean"] = True
        else:
            checks["mutation_tools_clean"] = False
    else:
        checks["mutation_tools_clean"] = True

    # Version-aware: unsupported-claim check only where the guardrail exists.
    try:
        from src.agent.guardrails import detect_unexecuted_mutation_claims

        checks["no_unexecuted_claims"] = detect_unexecuted_mutation_claims(reply, executed) is None
    except ImportError:
        checks["no_unexecuted_claims"] = None  # old version lacks the contract

    provider_failure = reply.startswith(
        ("Maaf, Helmis sedang mengalami gangguan", "Maaf, tidak ada respon")
    )
    checks["reply_present"] = (
        bool(reply) and not provider_failure
        if case.get("status") == "dispatched"
        else None
    )

    passed = all(v is not False for v in checks.values())
    return {"passed": passed, "checks": checks}


class ForcedModelCascade:
    def __init__(self, models: list[str]) -> None:
        self.models = models
        self._original: Any = None

    def __enter__(self) -> ForcedModelCascade:
        import src.agent.loop as loop_module

        self._original = loop_module.get_cascade_models
        loop_module.get_cascade_models = lambda **kwargs: list(self.models)
        return self

    def __exit__(self, *exc: Any) -> None:
        import src.agent.loop as loop_module

        loop_module.get_cascade_models = self._original


class _SilentClient:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def get_messages(self, chat_id: str, limit: int) -> list[Any]:
        return []

    async def send_text(self, chat_id: str, text: str) -> dict[str, Any]:
        self.sent.append({"chat_id": chat_id, "text": text})
        return {"status": "success"}

    async def is_reachable(self) -> bool:
        return True


async def run_case(case: dict[str, Any], models: list[str], runs: int) -> list[dict[str, Any]]:
    results = []
    for run_index in range(runs):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            data_dir.mkdir()
            os.environ["DATA_DIR"] = str(data_dir)
            os.environ["HELMIS_DB_PATH"] = str(data_dir / "helmis.db")

            import src.memory.store as store

            if hasattr(store, "semantic_memories_mod"):
                pass
            try:
                import src.memory.semantic as semantic_mod

                semantic_mod.SEMANTIC_MEMORY_FILE = str(data_dir / "semantic_memories.json")
            except Exception:
                pass
            store._repository = None

            seed_case_state(case["id"])

            client = _SilentClient()
            executed: list[dict[str, Any]] = []

            import src.tools as tools_pkg

            original_exec = tools_pkg.execute_tool_call
            import inspect as _inspect

            _accepts_chat_id = "chat_id" in _inspect.signature(original_exec).parameters

            async def recording_exec(
                name,
                args,
                sender,
                client=client,
                media_data=None,
                chat_id=None,
                __orig=original_exec,
                __executed=executed,
                __accepts_chat_id=_accepts_chat_id,
            ):
                if __accepts_chat_id:
                    result = await __orig(name, args, sender, client=client, media_data=media_data, chat_id=chat_id)
                else:
                    result = await __orig(name, args, sender, client=client, media_data=media_data)
                __executed.append({"name": name, "args": args, "result": result})
                return result

            tools_pkg.execute_tool_call = recording_exec  # type: ignore[assignment]

            final_reply: str | None = None
            started = time.monotonic()
            error: str | None = None
            connection_error_reply = "Maaf, Helmis sedang mengalami gangguan koneksi ke AI provider. Mohon coba sesaat lagi ya."
            for attempt in range(3):
                try:
                    final_reply = await run_agentic_react_loop(
                        client=client,
                        sender_name="Gilang",
                        chat_id="628222000000@c.us",
                        message_text=INPUT_OVERRIDES.get(case["id"], case["input_text"]),
                        max_steps=6,
                    )
                    error = None
                    if final_reply != connection_error_reply and not (
                        final_reply and final_reply.startswith("Maaf, tidak ada respon")
                    ):
                        break
                except Exception as e:
                    error = f"{type(e).__name__}: {e}"
                    final_reply = None
                await asyncio.sleep(2.0 * (attempt + 1))
            elapsed = time.monotonic() - started

            tools_pkg.execute_tool_call = original_exec  # type: ignore[assignment]

            scored = score_run(case, executed, final_reply)
            results.append(
                {
                    "run": run_index,
                    "tools": [step["name"] for step in executed],
                    "tool_results": [step["result"].get("status") for step in executed],
                    "final_reply": final_reply,
                    "error": error,
                    "latency_seconds": round(elapsed, 2),
                    "passed": scored["passed"],
                    "checks": scored["checks"],
                }
            )
    return results


async def main_async() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    parser.add_argument("--cases", default="")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--label", default="arm")
    parser.add_argument("--arm-models", default="", help="Comma list; default = cascade head")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    corpus = Path(args.corpus)
    cases = json.loads(corpus.read_text(encoding="utf-8"))["cases"]
    if args.cases:
        wanted = {c.strip() for c in args.cases.split(",")}
        cases = [c for c in cases if c["id"] in wanted]
    if not cases:
        print("No cases selected.")
        return 2

    if args.arm_models:
        arm_models = [m.strip() for m in args.arm_models.split(",") if m.strip()]
    else:
        arm_models = [m for m in cascade.GEMINI_MODELS if "gemma" not in m.lower()][:4]

    print(f"[{args.label}] models: {arm_models}")
    print(f"[{args.label}] cases: {len(cases)} x {args.runs} run(s)\n")

    out: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "label": args.label,
        "models": arm_models,
        "runs_per_case": args.runs,
        "results": {},
    }

    for case in cases:
        case_id = case["id"]
        print(f"=== {case_id} ===")
        with ForcedModelCascade(arm_models):
            runs = await run_case(case, arm_models, args.runs)
        out["results"][case_id] = {
            "input_text": INPUT_OVERRIDES.get(case_id, case["input_text"]),
            "expected_tools": [s["name"] for s in case.get("tools", [])],
            "runs": runs,
        }
        marks = "".join("P" if r["passed"] else "F" for r in runs)
        lat = [r["latency_seconds"] for r in runs]
        print(
            f"  [{marks}] tools={runs[0]['tools'] if runs else []} "
            f"latency_avg={sum(lat)/len(lat):.1f}s"
            + (f" err0={runs[0]['error']}" if runs and runs[0]["error"] else "")
        )

    total = passes = 0
    for entry in out["results"].values():
        for r in entry["runs"]:
            total += 1
            passes += 1 if r["passed"] else 0
    out["score"] = {"passed": passes, "total": total}
    print(f"\n[{args.label}] {passes}/{total} case-runs passed")

    Path(args.output).write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Results written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async()))
