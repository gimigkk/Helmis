# Agent Core & ReAct Execution Engine

This document details the internal reasoning engine of Helmis: the autonomous **ReAct Agent Loop**, the **Gemini Multi-Key Cascade**, **Mid-Turn Mailbox Steering**, **State Fidelity Guardrails**, **Polymorphic Tool Execution**, and **Turn Tracing**.

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
- **Max Iterations**: Capped at 12 ReAct steps per turn to prevent infinite tool loops.
- **Outcome Verification**: When tools mutate memory (e.g. `add_task`, `save_vault_file`), the agent inspects the returned status dictionary before stating success to the user.

---

## 2. Polymorphic Tool Registry (`src/tools/registry.py`)

Tools are registered declaratively using the `@register_tool` decorator and dispatched via the universal `execute_tool_call()` runner:

### Core Tool Capabilities
- **Task & Schedule Management (`tasks.py`)**:
  - `add_task`: Supports `task_type="reminder"` (human tasks with lead buffers & nags) and `task_type="scheduled_action"` (autonomous bot jobs with polymorphic `job` descriptors).
  - `list_tasks`: Urgency-sorted listing with filtering by `status` (`pending`, `completed`, `all`) and `task_type`.
  - `update_task` & `complete_task`: Full lifecycle updates, rescheduling, and status management.
- **Document Vault & Media (`files.py`, `vault.py`, `ocr.py`, `whatsapp.py`)**:
  - `read_vault_file`: Hybrid intra-page document reader. Extracts digital text instantly, while automatically running Gemini Multimodal Vision OCR on scanned/raster PDF pages, diagram/chart images, LaTeX math formulas, code screenshots, and Office formats (`.docx`, `.pptx`, `.xlsx`).
  - `send_vault_file`: Dispatches files from the vault. Supports `as_document=False` (native inline photo preview bubble) and `as_document=True` (lossless uncompressed document file).
  - Clean Media Delivery: Zero redundant `Dokumen: <filename>` caption clutter; respects WhatsApp's native UI cards.
- **PDF & Document Manipulation Toolkit (`pdf_ops.py`, `pdf_engine.py`)**:
  - `process_pdf`: Unified polymorphic tool supporting `merge` (native zero-margin or uniform A4), `split` (page slicing & rotation), `render_image` (PNG/JPG photo preview), `images_to_pdf` (photos to PDF), `to_docx` (PDF ➔ Word), `from_docx` (Word ➔ PDF), and `compress` (stream optimization).
- **On-Demand Skill Engine (`skills.py`)**:
  - `load_skill`: Dynamically loads domain playbooks (e.g. `pdf-toolkit`) into working memory on-demand.
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

To ensure 24/7 high availability, zero quota downtime, and rapid recovery from rate limits (`429`), Helmis implements dynamic API model discovery, multi-key rotation, and latency-optimized cascade sorting.

### Model Discovery & Tier Prioritization
1. **Flash-Lite Tier (Sub-Second Latency)**: `gemini-flash-lite-latest`, `gemini-2.5-flash-lite`, `gemini-3.5-flash-lite`, `gemini-3.1-flash-lite-preview`. (Prioritized first for instant WhatsApp replies).
2. **Flash Tier (Standard Multimodal & Reasoning)**: `gemini-flash-latest`, `gemini-3.7-flash`, `gemini-2.5-flash`, `gemini-3.5-flash`.
3. **Pro Tier (Complex Multimodal & Deep Extraction)**: `gemini-2.5-pro`, `gemini-pro-latest`.
4. **Modality Filtering**: For video processing turns, `flash-lite` models are automatically bypassed in favor of full Flash/Pro models to guarantee multimodal video compliance.

### Multi-Key Round-Robin Rotation
- Configured via `GEMINI_KEY_1`, `GEMINI_KEY_2`, `GEMINI_KEY_3`, etc.
- Each key is assigned to independent Google Cloud quotas.
- When an API key encounters a `ResourceExhausted` (`429`) or server error (`503`), the cascade immediately rotates to the next available key and model tier without failing the user request.

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
4. **Contextual Footnote Chips (`format_tool_chips`)**:
   - Dynamic footnote generation resolves generic tools into transparent chips (`↳ read_google_sheet`, `↳ complete_task`, `↳ save_vault_file`).
   - Strips synthetic or mimicked footnote chips produced by the LLM.

---

## 6. Task & Timeline Layout Standards

All multi-item listings and timelines generated by Helmis follow strict WhatsApp scannability standards:
1. **Sequential Numbering**: Clear numbered items (`1.`, `2.`, `3.`).
2. **Hierarchical Sub-lines**: Indented sub-lines (`   └ Deadline: ...`, `   └ Keterangan: ...`).
3. **Double Spacing**: Blank lines (`\n\n`) between distinct items to prevent walls of text.
4. **Default Assignee Separation**: Automatic grouping into `*Tugas Gilang:*`, `*Tugas Bunga:*`, `*Tugas Bersama:*`, and `*Tindakan Otomatis Helmis:*`.
5. **Header Blockquote Consistency**: Only the single main document title uses `>`, while section headers use clean bold text.

---

## 7. Execution Tracer (`src/agent/tracer.py`)

Every turn produces structured trace logs recorded to `data/agent_traces.jsonl` and formatted with color-coded ANSI output in the server console:

- **Incoming Message Event**: Timestamp, sender, message length, attachments.
- **Tool Invocations**: Tool name, arguments, execution duration (ms), return status.
- **Cascade Fallbacks**: Model switches, key rotations, retry latencies.
- **Final Outcome**: Generated text, bubble count, total execution time.
