# Communication & Message Routing

This document details how Helmis connects to WhatsApp via WAHA (WhatsApp HTTP API), dynamically routes media types, normalizes payloads, handles per-chat debounce queues, resolves group chat dynamics, and processes multimodal inputs.

---

## 1. WAHA Integration Architecture (`src/whatsapp/client.py`)

Helmis uses **WAHA (WhatsApp HTTP API)** with the **GOWS (Go-based WebSocket)** engine for lightweight, low-latency, self-hosted connectivity.

- **Inbound**: WAHA receives WebSocket events from WhatsApp servers and forwards them as HTTP POST requests to `http://agent:8644/webhooks/waha`.
- **Outbound Text**: Plain text messages are sent via `/api/sendText`.
- **Outbound Media Routing**: Media dispatches are dynamically routed to native WhatsApp endpoints based on MIME type and the `as_document` flag:
  - **Images (`image/*`, `.jpg`, `.png`, `.webp`)**: Routed to `/api/sendImage` for native inline photo bubbles.
  - **Videos (`video/*`, `.mp4`, `.mov`, `.webm`)**: Routed to `/api/sendVideo` for inline playable video bubbles.
  - **Voice Notes (`audio/*`, `.ogg`, `.opus`)**: Routed to `/api/sendVoice` for playable voice note bubbles.
  - **Documents (`application/*`, `.pdf`, `.zip`, or `as_document=True`)**: Routed to `/api/sendFile` for clean uncompressed document cards without quality loss.
- **Retry & Rate Limiting**: The client features exponential backoff retry for transient network glitches and typing keep-alives.

---

## 2. Inbound Payload Normalization (`src/whatsapp/parser.py`)

Incoming WhatsApp payloads vary across WAHA engines (GOWS, NOWEB, WEBJS). `parser.py` normalizes all payloads into a consistent `IncomingMessageEvent`:

```python
class IncomingMessageEvent(BaseModel):
    message_id: str
    chat_id: str
    sender_phone: str
    sender_name: str
    text: str
    has_media: bool = False
    media_url: str | None = None
    media_filename: str | None = None
    quoted_stanza_id: str | None = None
    quoted_participant: str | None = None
    quoted_text: str | None = None
    quoted_type: str | None = None
```

### Quoted / Replied Message Handling
- Automatically extracts quoted text, quoted sender name, and quoted media URLs across all engine payload variants.
- Formats quoted context cleanly into the prompt turn (`> [Sender]: "Quoted text"`).

---

## 3. FIFO Debounce Queue (`src/whatsapp/queue.py`)

Humans often send thoughts across multiple consecutive messages in rapid succession (e.g. *"Btw"*, *"Besok ada meeting jam 3"*, *"Tolong catet ya"*).

### Debounce Mechanism
1. When a message arrives, it is placed in the chat's FIFO queue.
2. A **1.0-second debounce timer** is started.
3. If additional messages arrive for the same chat within 1.0s, the timer resets and messages are coalesced into a single batch.
4. Once the burst ceases, the combined messages are dispatched to the processor as a single, coherent turn.

---

## 4. Turn Processing & Multi-Bubble Splitting (`src/whatsapp/processor.py`)

The turn processor orchestrates the execution lifecycle and dispatches final responses to WhatsApp.

### Conscious Multi-Bubble Splitting (`---`)
- The agent has conscious agency over WhatsApp message bubbles.
- Responses containing `---` on its own line are split into distinct bubbles sent sequentially with realistic human typing delays (0.8s to 1.5s).
- **Rule**: Single cohesive structures (class schedules, task lists, code, tables) are never split with `---`.

### Typing Presence & Progress Watchdog (long-turn UX)
- **Typing keepalive** (`_keep_typing`): re-asserts typing presence every 7.5s; errors are caught **per ping** so one WAHA hiccup never kills typing for the rest of the turn.
- **Progress watchdog**: at 12s and then every 30s while nothing has been dispatched, sends a liveness ping that **states the actual activity** — current tool + key argument (e.g. "_Helmis sedang memperbarui catatan tugas 'Absen Seminar Akuntansi' (42s)..._"), or the last completed tool between steps ("_`add_task` selesai (42s), Helmis sedang menyusun langkah berikutnya..._"), or an intent description before the first tool. Generic "masih diproses" filler is not used; `describe_intent_action` covers task/note/memory/web/vault/schedule/sandbox tool families.
- Silence now has a floor: a user never stares at a dead chat for >30s without knowing what the agent is doing.

---

## 5. Group Chat Dynamics & Non-Intervention

In the shared couple group chat (*Trio Helmis* with Gilang and Bunga):

### Pronoun Resolution
- Second-person pronouns (*"km"*, *"kamu"*, *"lu"*, *"sayang"*, *"beb"*) from Gilang refer to **Bunga**; from Bunga they refer to **Gilang**.
- Never assume the assistant is being addressed unless called by name (*"Helmis"*, *"mis"*) or given an explicit secretary command.

### Non-Intervention Mandate (`[NO_REPLY]`)
- When users talk to each other, answer each other's questions, quote each other, or exchange casual banter, the agent remains completely silent by outputting `[NO_REPLY]`.
- The webhook receiver detects `[NO_REPLY]` and aborts message dispatching without sending any message to WhatsApp.
