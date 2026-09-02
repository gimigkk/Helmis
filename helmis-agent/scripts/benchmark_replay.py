"""
benchmark_replay.py — Empirical A/B model benchmark on the production corpus.

Replays the 14 sanitized production cases against two model configurations
using identical state (fresh isolated SQLite DB per case), identical tools,
and identical prompts. The only variable is the model selection strategy:

  A (cascade):  the production cascade order from src.agent.cascade
                (flash-lite family first, ascending capability)
  B (baseline): a single stronger model (default gemini-2.5-pro)

For each case the harness:
  1. builds a fresh isolated state directory,
  2. seeds any state the case depends on (minimal seed set below),
  3. runs run_agentic_react_loop with the candidate model list forced,
  4. records tool sequence, outcomes, final reply, steps, latency,
  5. scores the run against the case's recorded invariants:
       - exact/required tool sequence match,
       - mutation claims authorized by executed tools,
       - no-fluff cases: byte-exact reply.

Results are written to docs/production-evidence/model_benchmark_results.json
(next to the corpus) and printed as a compact table.

Usage (from helmis-agent/):
    set -a; source ../.env; set +a
    ./.venv/bin/python scripts/benchmark_replay.py [--cases id,id2] [--runs N] \
        [--baseline gemini-2.5-pro] [--output PATH]

Requires GEMINI_KEY_* environment variables. Costs real API quota; the corpus
is intentionally small (14 cases x 2 configs) to bound spend.
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
CORPUS_PATH = REPO_ROOT / "docs" / "production-evidence" / "regression_cases.json"

# ISOLATION: point every store/semantic path at a scratch dir BEFORE any
# src import happens (modules read DATA_DIR at import time).
_ISOLATION_DIR = Path(tempfile.gettempdir()) / "helmis_benchmark_isolation"
_ISOLATION_DIR.mkdir(parents=True, exist_ok=True)
os.environ["DATA_DIR"] = str(_ISOLATION_DIR)
os.environ["HELMIS_DB_PATH"] = str(_ISOLATION_DIR / "helmis.db")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.agent import cascade  # noqa: E402
from src.agent.loop import run_agentic_react_loop  # noqa: E402
from src.memory.store import add_task  # noqa: E402

# ---------------------------------------------------------------------------
# Per-case state seeding: the minimum state each case assumes to exist.
# Kept minimal and explicit; a case with no seed runs on an empty store.
# ---------------------------------------------------------------------------

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


def seed_case_state(case_id: str, data_dir: Path) -> None:
    tasks = SEEDERS.get(case_id, [])
    for spec in tasks:
        try:
            add_task(**spec)
        except Exception as e:  # pragma: no cover - seeding is best-effort
            print(f"    seed warning: {spec.get('title')}: {e}")


# ---------------------------------------------------------------------------
# Scoring against recorded invariants
# ---------------------------------------------------------------------------

def score_run(case: dict[str, Any], executed: list[dict[str, Any]], final_reply: str | None) -> dict[str, Any]:
    expected_tools = [step["name"] for step in case.get("tools", [])]
    actual_tools = [step["name"] for step in executed]

    checks: dict[str, Any] = {}

    # 1. Tool sequence: exact order matters for mutation-heavy cases.
    if expected_tools:
        checks["tool_sequence_exact"] = actual_tools == expected_tools
        checks["tool_sequence_prefix"] = (
            actual_tools[: len(expected_tools)] == expected_tools[: len(actual_tools)]
            and len(actual_tools) >= min(1, len(expected_tools))
        )
    else:
        checks["tool_sequence_exact"] = actual_tools == []
        checks["tool_sequence_prefix"] = True

    # 2. Result statuses: every executed tool should have succeeded.
    checks["all_tools_succeeded"] = all(
        step.get("result", {}).get("status") == "success" for step in executed
    ) if executed else True

    # 3. No-fluff cases: reply must be byte-exact.
    if "no-fluff" in str(case.get("id", "")) or case.get("id") == "explicit-no-tool":
        expected_reply = str(case["final_reply"]).split("\n\n↳")[0]
        checks["reply_exact"] = (final_reply or "").strip() == expected_reply.strip()
    else:
        checks["reply_exact"] = None

    # 4. Mutation claims must be backed by executed tools (guardrail co-check).
    from src.agent.guardrails import detect_unexecuted_mutation_claims

    checks["no_unexecuted_claims"] = detect_unexecuted_mutation_claims(final_reply or "", executed) is None

    # 5. Reply must exist for dispatched cases; provider-failure replies never pass.
    provider_failure = (final_reply or "").startswith(
        ("Maaf, Helmis sedang mengalami gangguan", "Maaf, tidak ada respon")
    )
    checks["reply_present"] = (
        bool((final_reply or "").strip()) and not provider_failure
        if case.get("status") == "dispatched"
        else None
    )

    passed = all(v is not False for v in checks.values())
    return {"passed": passed, "checks": checks}


# ---------------------------------------------------------------------------
# Model forcing: pin the candidate list without touching cascade module state
# ---------------------------------------------------------------------------

class ForcedModelCascade:
    """Patch get_cascade_models so the loop uses one fixed candidate order."""

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


class _NullTracer:
    def log_step(self, **kwargs: Any) -> None:  # pragma: no cover
        pass


class _SilentClient:
    """Client seam: history fetch fails closed, sends are recorded."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def get_messages(self, chat_id: str, limit: int) -> list[Any]:
        return []

    async def send_text(self, chat_id: str, text: str) -> dict[str, Any]:
        self.sent.append({"chat_id": chat_id, "text": text})
        return {"status": "success"}

    async def is_reachable(self) -> bool:
        return True


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------

async def run_case(
    case: dict[str, Any],
    models: list[str],
    runs: int,
) -> list[dict[str, Any]]:
    results = []
    for run_index in range(runs):
        # Fresh isolated state per run: tmp data dir per (case, run, config).
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            data_dir.mkdir()
            os.environ["DATA_DIR"] = str(data_dir)
            os.environ["HELMIS_DB_PATH"] = str(data_dir / "helmis.db")

            # Modules read DATA_DIR at import time; re-point their path
            # constants for this run, then reset cached state.
            import src.memory.semantic as semantic_mod
            import src.memory.store as store

            semantic_mod.SEMANTIC_MEMORY_FILE = str(data_dir / "semantic_memories.json")
            store._repository = None

            seed_case_state(case["id"], data_dir)

            client = _SilentClient()
            executed: list[dict[str, Any]] = []

            # Capture executed tools by wrapping the package-level
            # execute_tool_call binding the loop imports at call time.
            import src.tools as tools_pkg

            original_exec = tools_pkg.execute_tool_call

            async def recording_exec(
                name,
                args,
                sender,
                client=client,
                media_data=None,
                chat_id=None,
                __orig=original_exec,
                __executed=executed,
            ):
                result = await __orig(name, args, sender, client=client, media_data=media_data, chat_id=chat_id)
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
                        message_text=case["input_text"],
                        max_steps=6,
                    )
                    error = None
                    # Retry only provider-failure replies; real model answers stand.
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
    parser.add_argument("--cases", default="", help="Comma-separated case IDs (default: all)")
    parser.add_argument("--runs", type=int, default=1, help="Runs per case per config")
    parser.add_argument(
        "--baseline",
        default="gemini-3.5-flash",
        help="Baseline model for arm B (stronger single model)",
    )
    parser.add_argument("--output", default=str(CORPUS_PATH.parent / "model_benchmark_results.json"))
    args = parser.parse_args()

    cases = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))["cases"]
    if args.cases:
        wanted = {c.strip() for c in args.cases.split(",")}
        cases = [c for c in cases if c["id"] in wanted]
    if not cases:
        print("No cases selected.")
        return 2

    cascade_models = [m for m in cascade.GEMINI_MODELS if "gemma" not in m.lower()]
    arm_a = cascade_models[:4]
    arm_b = [args.baseline]
    print(f"Arm A (cascade head): {arm_a}")
    print(f"Arm B (baseline):     {arm_b}")
    print(f"Cases: {len(cases)} x {args.runs} run(s) each\n")

    out: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "arm_a_cascade_head": arm_a,
        "arm_b_baseline": arm_b,
        "runs_per_case": args.runs,
        "results": {},
    }

    for case in cases:
        case_id = case["id"]
        print(f"=== {case_id} ===")
        entry: dict[str, Any] = {"input_text": case["input_text"], "expected_tools": [s["name"] for s in case.get("tools", [])]}
        for arm_name, models in (("cascade", arm_a), ("baseline", arm_b)):
            with ForcedModelCascade(models):
                runs = await run_case(case, models, args.runs)
            entry[arm_name] = runs
            marks = "".join("P" if r["passed"] else "F" for r in runs)
            lat = [r["latency_seconds"] for r in runs]
            print(
                f"  {arm_name:9s} [{marks}] "
                f"tools={runs[0]['tools'] if runs else []} "
                f"latency_avg={sum(lat)/len(lat):.1f}s"
                + (f" err0={runs[0]['error']}" if runs and runs[0]["error"] else "")
            )
        out["results"][case_id] = entry
        print()

    # Summary
    for arm_name in ("cascade", "baseline"):
        total = passes = 0
        for entry in out["results"].values():
            for r in entry[arm_name]:
                total += 1
                passes += 1 if r["passed"] else 0
        out[f"{arm_name}_score"] = {"passed": passes, "total": total}
        print(f"{arm_name:9s}: {passes}/{total} case-runs passed")

    Path(args.output).write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nResults written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async()))
