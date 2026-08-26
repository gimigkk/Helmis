# Communication & Message Routing

This document details how Helmis connects to WhatsApp via WAHA (WhatsApp HTTP API), normalizes payloads, handles per-chat debounce queues, resolves group chat dynamics, and processes multimodal inputs.

---

## 1. WAHA Integration Architecture (`src/whatsapp/client.py`)

Helmis uses **WAHA (WhatsApp HTTP API)** with the **GOWS (Go-based WebSocket)** engine for lightweight, low-latency, self-hosted connectivity.

- **Inbound**: WAHA receives WebSocket events from WhatsApp servers and forwards them as HTTP POST requests to `http://agent:8644/webhooks/waha`.
- **Outbound**: The agent interacts with WAHA via REST API endpoints (`/api/sendText`, `/api/sendFile`, `/api/startTyping`, `/api/getMessages`).
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

---

## 5. Group Chat Dynamics & Non-Intervention

In the shared couple group chat (*Trio Helmis* with Gilang and Bunga):

### Pronoun Resolution
- Second-person pronouns (*"km"*, *"kamu"*, *"lu"*, *"sayang"*, *"beb"*) from Gilang refer to **Bunga**; from Bunga they refer to **Gilang**.
- Never assume the assistant is being addressed unless called by name (*"Helmis"*, *"mis"*) or given an explicit secretary command.

### Non-Intervention Mandate (`[NO_REPLY]`)
- When users talk to each other, answer each other's questions, quote each other, or exchange casual banter, the agent remains completely silent by outputting `[NO_REPLY]`.
- The webhook receiver detects `[NO_REPLY]` and aborts message dispatching without sending any message to WhatsApp.
