# Agent Core & ReAct Execution Engine

This document details the internal reasoning engine of Helmis: the autonomous **ReAct Agent Loop**, the **Gemini Multi-Key Cascade** (cooldowns + hedged racing), **Compact Query Mode**, the **Chat Fast Path**, **Mid-Turn Mailbox Steering**, **State Fidelity Guardrails**, **Polymorphic Tool Execution**, and **Turn Tracing**.

---

## 1. Autonomous ReAct Agent Loop (`src/agent/loop.py`)

Helmis operates an autonomous multi-step reasoning loop (Reason + Act) powered by Google Gemini. Rather than simply generating text, the agent evaluates state, calls Python tools, inspects verified disk outcomes, and synthesizes concise WhatsApp responses.

```mermaid
flowchart TD
    Start([Inbound Turn Initiated]) --> BuildPrompt[Load System Prompt + Active Skills + Working Memory]
    BuildPrompt --> FetchHistory[Load Recent WhatsApp Chat History]
    FetchHistory --> CallLLM[Invoke Gemini via Cascade]
    
    CallLLM --> CheckResponse{Response Type}
    
    CheckResponse -->|Final Text| CheckSteering{New User Messages in Mailbox?}
    CheckResponse -->|Tool Call| ExecTool[Execute Python Tool Handler via Registry]
    
    ExecTool --> RecordOutcome[Record Verified Result on Disk]
    RecordOutcome --> CheckSteering
    
    CheckSteering -->|Yes| InjectSteer[Inject Steering Message into Conversation Turn]
    CheckSteering -->|No| HasMoreTools{More Tool Steps Needed?}
    
    InjectSteer --> CallLLM
    HasMoreTools -->|Yes (<= 12 steps)| CallLLM
    HasMoreTools -->|No| Guardrail[State Fidelity Guardrail Verification]
    
    Guardrail --> Footnotes[Append ↳ Footnote Chips if tools used]
    Footnotes --> Dispatch[Dispatch WhatsApp Message Bubbles]
```

### Iteration Limits & Safeguards
- **Max Iterations**: Capped at 12 ReAct steps (absolute ceiling 18 including mid-turn steering rewinds) per turn to prevent infinite tool loops.
- **Outcome Verification**: When tools mutate memory (e.g. `add_task`, `save_vault_file`), the agent inspects the returned status dictionary before stating success to the user.

---

## 2. Polymorphic Tool Registry (`src/tools/registry.py`)

Tools are registered declaratively using the `@register_tool` decorator and dispatched via the universal `execute_tool_call()` runner:

### Core Tool Capabilities
- **Task & Schedule Management (`tasks.py`)**:
  - `add_task`: Supports `task_type="reminder"` (human tasks with lead buffers & nags) and `task_type="scheduled_action"` (autonomous bot jobs with polymorphic `job` descriptors).
  - `list_tasks`: Urgency-sorted listing with filtering by `status` (`pending`, `completed`, `all`) and `task_type`.
  - `update_task` & `complete_task`: Full lifecycle updates, rescheduling, and status management.
- **Universal Code Execution Sandbox (`code_exec.py`)**:
  - `execute_code`: Executes Python 3 in an isolated subprocess for arbitrary computation: date/time arithmetic in WIB, mathematical calculations, custom string/data parsing, and JSON/CSV processing without requiring bespoke tools.
- **Procedural Memory & Dynamic Skills (`skills.py`, `crystallize.py`)**:
  - `create_skill`: Allows user or agent to crystallize reusable procedures into persistent `SKILL.md` playbooks under `config/skills/`.
  - `update_skill`: Refines or appends to existing skill playbooks.
  - `list_skills`: Lists all operational skills available in the environment.
  - `load_skill`: Dynamically loads specialized on-demand playbooks into working memory.
- **Document Vault & Media (`files.py`, `vault.py`, `ocr.py`, `whatsapp.py`)**:
  - `read_vault_file`: Hybrid intra-page document reader. Extracts digital text instantly, while automatically running Gemini Multimodal Vision OCR on scanned/raster PDF pages, diagram/chart images, LaTeX math formulas, code screenshots, and Office formats (`.docx`, `.pptx`, `.xlsx`).
  - `send_vault_file`: Dispatches files from the vault. Supports `as_document=False` (native inline photo preview bubble) and `as_document=True` (lossless uncompressed document file).
  - Clean Media Delivery: Zero redundant `Dokumen: <filename>` caption clutter; respects WhatsApp's native UI cards.
- **PDF & Document Manipulation Toolkit (`pdf_ops.py`, `pdf_engine.py`)**:
  - `process_pdf`: Unified polymorphic tool supporting `merge` (native zero-margin or uniform A4), `split` (page slicing & rotation), `render_image` (PNG/JPG photo preview), `images_to_pdf` (photos to PDF), `to_docx` (PDF ➔ Word), `from_docx` (Word ➔ PDF), and `compress` (stream optimization).
- **Memory & Notes (`notes.py`, `memory.py`)**:
  - Persistent JSON and semantic vector memories.
- **Web & Google Workspace Reader Engine (`google_reader.py`, `web.py`)**:
  - `read_url`: Unified reader for public Google Docs, Sheets, Slides, Drive files, and generic web pages.
  - Contextual Aliases: `read_google_sheet`, `read_google_doc`, `read_google_slides`, `read_web_page`.
  - **Multi-Tab Published Sheets (`pubhtml`) Parser**: Standard `html.parser.HTMLParser` engine discovering JavaScript tabs and extracting tabular HTML into clean Markdown without external dependencies.
  - **Epistemic Humility**: Metadata `snapshot_at` WIB, `force_refresh=True` flag, and private document redirect detection (`accounts.google.com/ServiceLogin`).
  - **SSRF Safety**: Validates IPs against private/local ranges (`127.0.0.0/8`, `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `169.254.0.0/16`, etc.).


---

## 3. Gemini Multi-Key Cascade (`src/agent/cascade.py`)

To ensure 24/7 high availability, zero quota downtime, and rapid recovery from rate limits (`429`) and provider outages (`503`), Helmis implements dynamic API model discovery, multi-key rotation, model-level failure cooldowns, and hedged racing.

### Model Discovery & Tier Prioritization
1. **Flash Tier (Newest First)**: `gemini-3.8-flash`, `gemini-3.7-flash`, `gemini-3.6-flash`, `gemini-3.5-flash` (primary cascade window).
2. **Flash-Lite Tier (Fallback)**: `gemini-2.5-flash-lite`, `gemini-3.1-flash-lite`; the dead alias `gemini-flash-lite-latest` sinks to the very end (repeat timeouts).
3. **Pro Tier (Last Resort)**: `gemini-pro-latest` before dead aliases.
4. **Modality Filtering**: For video turns, `flash-lite` models are bypassed in favor of full Flash/Pro models and the per-call timeout rises to 25s (12s standard).

### Multi-Key Round-Robin Rotation
- Configured via `GEMINI_KEY_1` … `GEMINI_KEY_8` (both `AIza...` and `AQ....` key formats accepted; placeholders rejected).
- `429` (quota) and `503` (overload) rotate keys within a model; a model that `503`s on **every** key is model-level overloaded.
- Timeout/404 are model-level failures: the model is skipped immediately, never retried on another key.

### Model Cooldowns (`mark_model_unavailable`)
- Models failing at the model level (timeout, 404, 503-on-all-keys) enter a **120s cooldown**.
- Cooldown-aware ordering (`get_cascade_models_with_cooldown`) demotes (never drops) cooled models to the end, so subsequent ReAct steps start at healthy models instead of re-probing a dead head (a 503 storm previously cost 8 key attempts × ~1–3s per model per step).

### Hedged Racing (`_hedged_cascade_call`, `src/agent/loop.py`)
- The top-2 candidate models race with a staggered start: if the head has not answered within half the turn timeout, the second model fires and the **first 200-response wins**; the loser is cancelled.
- A hung head model therefore costs at most ~half the timeout instead of the full timeout (a hung `3.8-flash` previously taxed every turn its full 12s).
- A head that fails *fast* (503/timeout) falls straight to the sequential tail with no double wait.
- Final-synthesis calls reuse the same hedged path; cascade helpers return `(winning_model, response)` so tracer logs report the model that actually answered.

### Compact Mode (query turns)
- Turn plans with `intent == "query"` and a known data domain (task/schedule/note/memory/person/vault) run with:
  - **Compact system prompt** (`load_compact_system_prompt`): identity + §2 zero-assumption grounding + §4 formatting/layout contract + clock (~12k chars vs 19k full manual).
  - **Domain-scoped skills** (`load_domain_skills`): only the playbooks for that domain (e.g. task queries load task-manager/recurring-reminders/reminder-engine).
  - **Domain-scoped tools** (`get_compact_tools`, `src/tools/schema.py`): 8 relevant declarations vs 44 (31k → 9k chars), always including `load_skill`/`list_skills`/`execute_code` escape hatches.
  - **No semantic search** (query turns don't need long-term fact retrieval).
- Same model, same ReAct tool-calling contract: the model still decides filters, formatting, and follow-ups. Actions/chat/media turns keep the full manual and all 44 tools.

### Chat Fast Path (`src/agent/fastpath.py`)
- Pure greetings/acks ("halo", "makasih", "sip") run on a ~60-token prompt with the live clock; the model decides everything and may bail to the full loop via `[FALLBACK]`.
- If the provider is completely down, a deterministic time-aware greeting answers instead of failing.
- "jam berapa"/clock queries answer with **zero model calls**.
- All data queries (tasks/schedules/notes, filtered or not) deliberately go through the full agent loop — no phrase whitelists, no deterministic rendering of user data — so the model retains authority over meaning and formatting.

---

## 4. Mid-Turn Mailbox Steering & Binary Media Sync

Users frequently send rapid follow-up messages or corrections while the agent is actively executing long-running tools (e.g. *"Wait, cancel that"*, *"Also include Bunga"*, *"Actually make it 7 PM instead"*), or send file attachments 2–3 seconds after their initial text prompt.

### Mechanism
1. The `ChatQueueManager` maintains an active per-chat mailbox queue.
2. After each tool execution step (and before model calls), `agent_loop` invokes `drain_and_inject_mid_turn_mailbox()`.
3. **Binary Media Synchronization**: When a media attachment arrives mid-turn:
   - The binary bytes are downloaded and stored in `turn_state["media_data"]`.
   - Native `inlineData: {"mimeType": ..., "data": ...}` parts are injected into Gemini contents for images/PDFs.
   - Subsequent tool executions (such as `save_vault_file`) receive the updated binary payload directly.
4. **Voice Note Transcriptions**: Audio notes sent mid-turn are transcribed via Whisper/Gemini and injected into the prompt.
5. **Step Rewind Adaptif**: If mid-turn input is received, the step counter rewinds (`step = max(0, step - 3)`), granting up to 3 extra steps to fulfill the updated plan.

---

## 5. Two-Step Anti-Hallucination & State Mutation Guardrails (`src/agent/guardrails.py`)

To eliminate false confirmations where the model claims an action was performed without executing database tools, Helmis enforces a multi-layer state fidelity architecture:

### Invariants & Protection Layers
1. **Mutation Claim Detector (`detect_unexecuted_mutation_claims`)**:
   - Inspects model outputs for active mutation claims:
     - Task Completion (`complete_task`): *"sudah ditandai selesai"*, *"berhasil diselesaikan"*, etc.
     - Deletion (`delete_task`, `delete_note`, `delete_memory`): *"sudah dihapus"*, *"berhasil dihilangkan"*, etc.
     - Task Creation (`add_task`): *"sudah dicatat"*, *"berhasil dijadwalkan"*, etc.
     - Vault Saving (`save_vault_file`): *"tersimpan di brankas"*, *"sudah disimpan"*, etc.
     - Dispatch (`send_whatsapp_message`, `send_vault_file`): *"sudah dikirimkan ke"*, etc.
2. **Dynamic Turn Interception (`loop.py`)**:
   - If the model emits a mutation claim in Step 1 without calling the required tool, the text is **intercepted and rejected**.
   - A strict steering instruction is injected:
     `SYSTEM INTEGRITY FAULT: Kamu mengklaim telah melakukan tindakan, tetapi BELUM memanggil functionCall ke tool terkait! Eksekusi functionCall sekarang.`
   - The loop continues to Step 2 to force the `functionCall`.
3. **Fallback Fidelity Overrides**:
   - If the step limit is reached without tool execution, the hallucinated claim is overwritten with an honest message:
     `Mohon maaf, tindakan tersebut belum berhasil diproses di sistem database. Silakan ulangi perintah secara spesifik.`
4. **Transparent Engine Footnote Chips (`format_tool_chips`)**:
   - Dynamic footnote generation resolves generic tools into transparent, engine-annotated chips:
     - **Vision OCR**: `↳ read_vault_file:vision_ocr`, `↳ read_google_slides:vision_ocr`
     - **PubHTML Multi-Tab Parser**: `↳ read_google_sheet:pubhtml_parser`
     - **Digital PDF Text**: `↳ read_vault_file:digital_text`
     - **Office Native Parsers**: `↳ read_vault_file:pptx_parser`, `↳ read_vault_file:xlsx_parser`, `↳ read_vault_file:docx_parser`
     - **Direct Text / CSV**: `↳ read_google_sheet:csv_export`, `↳ read_google_doc:direct_text`
   - Strips synthetic or mimicked footnote chips produced hallucinated by the LLM.
   - **Enabled by default**: `HELMIS_TOOL_CHIPS_ENABLED` defaults ON (transparency by default); set `0`/`false`/`no` to opt out. No-fluff turns and `not_found`/error paths never carry chips.
5. **Honest Degraded Synthesis**:
   - Final synthesis rotates models×keys on the same hedged path as the main turn; if it still fails, the reply is a per-tool-count honest summary (e.g. "Helmis selesai memproses (add_task×3), tapi gagal menyusun rangkuman akhir") — never a fabricated "N tindakan berhasil" for actions that didn't run.

---

## 6. Task & Timeline Layout Standards

All multi-item listings and timelines generated by Helmis follow strict WhatsApp scannability standards:
1. **Sequential Numbering**: Clear numbered items (`1.`, `2.`, `3.`).
2. **Hierarchical Sub-lines**: Indented sub-lines (`   └ Deadline: ...`, `   └ Keterangan: ...`).
3. **Double Spacing**: Blank lines (`\n\n`) between distinct items to prevent walls of text.
4. **Default Assignee Separation**: Automatic grouping into `*Tugas Gilang:*`, `*Tugas Bunga:*`, `*Tugas Bersama:*`, and `*Tindakan Otomatis Helmis:*`.
5. **Header Blockquote Consistency**: Only the single main document title uses `>`, while section headers use clean bold text.

### Task Categories & Routine Filtering
- `add_task` accepts `category`: `work` (default) / `personal` / `shared` / `routine`.
- **Auto-detection** (`_detect_task_category`, `src/memory/store.py`): titles matching absen/kehadiran/kuliah/class/check-in/presensi → `routine`; work verbs (buat/kerjakan/isi/mengumpulkan…) override routine keywords (so "Membuat PPT untuk mata kuliah X" stays work). Recurrence alone never implies routine.
- **`list_tasks(include_routine=False)` is the default**: "ada tugas apa" means real work; the 8 weekly attendance pings stay out of overviews. `include_routine=True` is reserved for explicit routine asks (schema description teaches the model when to set it). The scheduler always sees all tasks — filtering is display-only, reminders still fire.
- The task tool schema and `config/skills/recurring-reminders/SKILL.md` document the category contract.

---

## 7. Execution Tracer (`src/agent/tracer.py`)

Every turn produces structured trace logs recorded to `data/agent_traces.jsonl` and formatted with color-coded ANSI output in the server console:

- **Incoming Message Event**: Timestamp, sender, message length, attachments.
- **Tool Invocations**: Tool name, arguments, execution duration (ms), return status.
- **Cascade Fallbacks**: Model switches, key rotations, retry latencies.
- **Final Outcome**: Generated text, bubble count, total execution time.

---

## 8. Pre-Emptive Intent Classification & Forced Tool Calling

To completely eliminate **Promissory Hallucinations** (e.g. the agent replying *"Sip, nanti reminder-nya gw geser"* without invoking `update_task`), Helmis uses pre-emptive intent routing:

1. **`classify_turn_intent(message_text)`**: Evaluates incoming message text before the first LLM call:
   - `action`: State mutation detected (snooze, delay, reschedule, create task, delete, save file).
   - `query`: Read-only inspection detected (list tasks, check schedule, search).
   - `chat`: Casual banter.
2. **Forced Function Calling (`mode: ANY`)**:
   - On step 0 with `action` intent, Helmis injects `toolConfig.functionCallingConfig.mode = "ANY"` into the Gemini API payload.
   - The LLM is **strictly prohibited from emitting text output** and must emit a valid tool call.
   - On subsequent steps, `mode` reverts to `AUTO` so the model can synthesize a final verified confirmation.
3. **Anti-Promissory Guardrail (`promissory_reschedule`)**:
   - Patterns catching future promises (*"nanti gw geser"*, *"akan gw ingatkan"*) are intercepted if no mutation tool was executed.

---

## 9. Autonomous Auto-Crystallization Engine (`src/agent/crystallize.py`)

Adopting the **Hermes Agent & Voyager pattern**, Helmis can autonomously synthesize new operational skill playbooks:

1. **Zero-Latency Fire-and-Forget**: When a multi-step workflow completes ($\ge 2$ unique non-trivial tools or complex `execute_code` routines), `asyncio.create_task()` launches a background reflection worker without delaying the WhatsApp response.
2. **Critic Reflection**: A lightweight LLM Critic reviews the trajectory against existing skills. If a novel, reusable procedure is identified, it generates a structured `SKILL.md` adhering to the `agentskills.io` standard.
3. **Persistent Procedural Memory**: The skill is saved to `config/skills/auto-<name>/SKILL.md` and becomes an active operational playbook across all future turns.

