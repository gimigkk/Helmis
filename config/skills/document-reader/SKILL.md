---
name: document-reader
description: >
  Read, summarise, and remember documents and images sent via WhatsApp.
  Uses Gemini vision. Stores summaries in memory for future reference.
---

# Document Reader Skill

## Purpose

Process any media or document sent by Gilang or Bunga and make it permanently
accessible via memory. "What was in that document?" should always work.

## Supported Types

- **Images**: photos, screenshots, receipts, handwritten notes, menus, signs
- **PDFs**: contracts, invoices, reports, tickets
- **Documents**: text files, spreadsheets (converted), presentations (summarised)

All are processed via Gemini's vision capabilities.

## Behaviour on Receipt

When a message arrives with media attached:

1. **Acknowledge immediately**: "Got it, reading this for you..."
2. **Process via vision**: extract all readable text and understand the content
3. **Generate a summary**: clear, structured, human-readable
4. **Store in memory**: tagged with sender, date, and document type
5. **Reply with the summary**

Do this automatically — don't ask "do you want me to read this?" Just read it.

## Memory Storage

Store in Hermes persistent memory tagged `document`.

Each document record has:
```
id: unique string (e.g. doc_20260101_001)
title: inferred from content (e.g. "Electricity Bill - July 2026")
type: "invoice" | "contract" | "photo" | "receipt" | "note" | "ticket" | "other"
sender: "Gilang" | "Bunga"
received_at: ISO 8601 datetime
summary: 2–5 sentence summary of the document
key_data: dict of important extracted values (amounts, dates, names, etc.)
media_url: original URL from WAHA (for reference)
```

Example `key_data` for an electricity bill:
```json
{
  "amount_due": "Rp 250.000",
  "due_date": "2026-09-10",
  "account_number": "1234567890",
  "period": "August 2026"
}
```

## Summary Format

**For documents with key data (bills, invoices, contracts):**
```
📄 [Document Title]

[2-3 sentence summary of what this document is]

Key details:
· Amount: [value]
· Due: [date]
· [Other key fields]

Saved to memory. You can ask me about this later.
```

**For photos/images:**
```
📷 [Brief description of image]

[What I can see: people, text, objects, context]

[Any readable text extracted verbatim if important]

Saved to memory.
```

## Recalling Documents

When asked about past documents:
- "What was in that bill I sent?" → retrieve most recent bill document
- "Show me the contract from last week" → retrieve by type and date
- "How much was the electricity bill?" → retrieve key_data from the relevant document

Use semantic memory search — match by content, not just exact title.

## OCR and Handwriting

For handwritten notes or low-quality scans:
- Extract what is legible
- Clearly note any parts that were unreadable: "[unclear]"
- Ask for clarification only if a critical part is missing
