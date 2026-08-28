# Memory Architecture & Persistent Storage

This document details Helmis's 3-tier local storage architecture: the **Atomic JSON Store** (`helmis_memory.json`), **Semantic Vector Memory** (`semantic_memories.json`), and the **Document Vault** (`data/vault/`).

---

## 1. Multi-Tier Storage Overview

All user data is stored locally on the server volume (`./data`) with zero external database dependencies.

```
data/
├── helmis_memory.json        # Atomic JSON Store: tasks, contacts, shared notes, schedules
├── file_catalog.json         # Document Vault metadata catalog
├── semantic_memories.json    # Vector Memory: episodic facts with Gemini 3072-dim embeddings
├── sandbox/                  # Ephemeral Temp Sandbox: downloaded URL snapshots, converted sheets (TTL 30m)
├── vault/                    # Binary storage for PDFs, scans, receipts, and project files
│   ├── health/               # Medical records, prescriptions, lab results
│   ├── id_cards/             # Identity cards, passports, SIM, family cards
│   ├── travel/               # Flight tickets, boarding passes, hotel bookings
│   ├── receipts/             # Invoices, transfer receipts, bills, warranties
│   ├── documents/            # CV, contracts, academic diplomas, modules
│   ├── media/                # Saved photos, videos, audio clips
│   └── projects/             # Custom project workspace folders
└── agent_traces.jsonl        # Structured execution traces
```

---

## 2. Atomic JSON Store (`src/memory/store.py`)

Handles structured records (tasks, people directory, notes, schedules) using atomic writes with file locking (`fcntl`) to guarantee zero corruption under concurrent read/writes.

### Data Schemas
- **Tasks**: `id`, `title`, `assignee` (`"Gilang" | "Bunga" | "Both"`), `due_date`, `due_time`, `priority` (`"low" | "normal" | "urgent"`), `lead_time_minutes`, `status` (`"todo" | "in-progress" | "completed"`), `reminded_stages`.
- **People**: `id`, `name`, `relationship`, `phone`, `email`, `notes`, `updated_at`.
- **Notes**: `id`, `title`, `category`, `content`, `updated_at`.

---

## 3. Semantic Vector Memory (`src/memory/semantic.py`)

Maintains long-term episodic memory using Google Gemini's `text-embedding-004` (or `gemini-embedding-001`) with cosine similarity search.

### Key Capabilities
- **Background Extraction**: Automatically extracts facts, preferences, and personal routines after each conversation turn.
- **Timestamp Tagging**: Every memory is tagged with `[Recorded: YYYY-MM-DD]`.
- **Temporal Memory Supersession**: When past and present routines conflict (e.g. old semester class schedule vs new semester schedule), the agent dynamically prioritizes the more recent timestamp as active ground truth.

---

## 4. Document Vault (`src/memory/vault.py`)

A secure, structured document management system for PDFs, documents, images, and project files.

### Ingestion & Filename Preservation Invariant
- **Named Documents**: Always preserves the original uploaded filename (e.g. `P2_Gilang_M0403241117_02.pdf`). Synthetic slugs are never generated for named files.
- **Generic Media**: Unnamed camera captures (`IMG-...`, `image.jpeg`) receive clean descriptive slugs based on visual content (e.g. `scan_bpjs_kesehatan_gilang.jpg`).

### Inspection & Extraction
- **Hybrid PDF Reader & `force_ocr`**: Utilizes `pymupdf` to extract digital text layers instantly. For scanned/raster image pages (≤ 30 characters) or when `force_ocr=true` is requested (*"process by image"*, *"cek visualnya"*), automatically renders 150 DPI page pixmaps and invokes Gemini Multimodal Vision OCR.
- **Microsoft Office Parsers**:
  - `.docx` via `python-docx`: Extracts structured headings, paragraphs, and markdown tables.
  - `.pptx` via `python-pptx`: Extracts slide boundaries (`--- Slide N dari Total ---`), slide titles, bullet points, speaker notes, and embedded picture OCR.
  - `.xlsx` via `openpyxl`: Converts worksheets and column headers into clean tabular Markdown.
- **Image OCR**: Automatically runs Gemini Vision OCR on standalone images (`.png`, `.jpg`, `.jpeg`, `.webp`) and caches results into `ocr_summary`.
- **Search & Dispatch**: Supports keyword search (`search_vault_files`), text inspection (`read_vault_file`), and direct dispatch over WhatsApp (`send_vault_file`).
- **Google Workspace Reader (`src/tools/google_reader.py`)**:
  - **Published Google Sheets (`pubhtml`)**: Multi-tab extraction across all worksheet tabs (`[FS]`, `[DS]`, `[AE]`), resolving individual tab sub-sheets.
  - **Google Slides & PDF Downloads**: Renders visual presentation slides to 150 DPI images with multimodal diagram OCR.
  - **Link/Bookmark Routing**: URLs stored in shared notes automatically trigger `read_url` upon user inquiry.

---

## 5. Temp Sandbox Workspace (`src/memory/sandbox.py`)

An isolated ephemeral workspace (`data/sandbox/` or `/app/data/sandbox/`) dedicated to temporary downloads, Google Workspace snapshot caches, and intermediate conversion files.

### Key Capabilities & Safeguards
- **Zero Vault Pollution**: Prevents temporary web snapshots from cluttering `file_catalog.json` and permanent vault directories.
- **TTL Cache (30 Minutes)**: Downloaded URLs and parsed tables are cached with a 30-minute Time-To-Live, reducing repeated network requests.
- **Auto-Cleanup Engine**: Automatically prunes files older than 1 hour or purges the oldest files (LRU) when sandbox directory size exceeds 250MB.
- **Path Traversal Protection**: Uses `is_safe_sandbox_path()` to ensure all read/write operations remain strictly confined to the sandbox folder.
- **Atomic Operations**: Employs atomic write mechanisms (`.tmp` write followed by atomic rename) to avoid corrupted files if the process is terminated mid-write.

---

## 6. Multimodal Vision OCR Engine (`src/memory/ocr.py`)

A high-precision document and image OCR engine leveraging the Google Gemini Vision multimodal API with multi-key rotation and zero-hallucination structured markdown prompting.

### Key Features
- **Dynamic Key Failover**: Rotates across all available `GEMINI_KEY_*` environment keys with automatic rate-limit (429) backoff.
- **Strict Markdown Schema**: Prompts the vision model to output tables, forms, signatures, and stamps directly as clean Markdown without conversational preamble.
- **Automatic Caching**: Persists extracted text into `file_catalog.json` (`ocr_summary`), eliminating repeated API calls and ensuring 0ms retrieval on subsequent reads.
