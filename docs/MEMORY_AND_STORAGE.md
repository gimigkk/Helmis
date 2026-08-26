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
- **PDF Text Layer Extraction**: Utilizes `pypdf` to extract text from digital PDF pages without needing expensive vision tokens.
- **Image OCR**: Inspects scanned receipts, tickets, and photos.
- **Search & Dispatch**: Supports keyword search (`search_vault_files`), text inspection (`read_vault_file`), and direct dispatch over WhatsApp (`send_vault_file`).
