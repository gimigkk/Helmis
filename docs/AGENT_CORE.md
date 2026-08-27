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
- **Document Vault & Media (`files.py`, `whatsapp.py`)**:
  - `send_vault_file`: Dispatches files from the vault. Supports `as_document=False` (native inline photo preview bubble) and `as_document=True` (lossless uncompressed document file).
  - Clean Media Delivery: Zero redundant `Dokumen: <filename>` caption clutter; respects WhatsApp's native UI cards.
- **PDF & Document Manipulation Toolkit (`pdf_ops.py`, `pdf_engine.py`)**:
  - `process_pdf`: Unified polymorphic tool supporting `merge` (native zero-margin or uniform A4), `split` (page slicing & rotation), `render_image` (PNG/JPG photo preview), `images_to_pdf` (photos to PDF), `to_docx` (PDF ➔ Word), `from_docx` (Word ➔ PDF), and `compress` (stream optimization).
- **On-Demand Skill Engine (`skills.py`)**:
  - `load_skill`: Dynamically loads domain playbooks (e.g. `pdf-toolkit`) into working memory on-demand.
- **Memory & Notes (`notes.py`, `memory.py`)**:
  - Persistent JSON and semantic vector memories.
- **Live Search & External Context (`web.py`)**:
  - Real-time search integration.

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

## 4. Mid-Turn Mailbox Steering

Users frequently send rapid follow-up messages or corrections while the agent is actively executing long-running tools (e.g. *"Wait, cancel that"*, *"Also include Bunga"*, *"Actually make it 7 PM instead"*).

### Mechanism
1. The `ChatQueueManager` maintains an active per-chat mailbox queue.
2. After each tool execution step, `agent_loop` queries `mailbox.get_pending_messages()`.
3. If new messages arrived during tool execution, they are injected into the active prompt as mid-turn user steering context:
   ```text
   [SYSTEM: While you were processing, the user sent an additional follow-up:
   "<new message content>"
   Incorporate this new instruction immediately into your ongoing action plan.]
   ```
4. The agent dynamically adjusts its remaining steps without restarting the turn from scratch.

---

## 5. State Fidelity Guardrails (`src/agent/guardrails.py`)

To prevent hallucinations, Helmis enforces strict fidelity checking between tool execution results and final generated responses.

### Verification Invariants
1. **State Mutation Fidelity**: If the assistant response claims a task was added or completed, the turn must have successfully executed `add_task` or `complete_task`.
2. **Document Vault Fidelity**: If the assistant quotes line items from a vault document, `read_vault_file` or `search_vault_files` must have been called.
3. **↳ Footnote Generation**: When tools are executed, clean visual footnote chips are generated for transparency:
   ```text
   Sip Gilang, tiket pesawat udah disimpan di vault ya.
   ↳ `save_vault_file`, `add_task`
   ```

---

## 6. Execution Tracer (`src/agent/tracer.py`)

Every turn produces structured trace logs recorded to `data/agent_traces.jsonl` and formatted with color-coded ANSI output in the server console:

- **Incoming Message Event**: Timestamp, sender, message length, attachments.
- **Tool Invocations**: Tool name, arguments, execution duration (ms), return status.
- **Cascade Fallbacks**: Model switches, key rotations, retry latencies.
- **Final Outcome**: Generated text, bubble count, total execution time.
