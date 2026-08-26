---
name: document-reader
description: Read, extract, summarize, and remember documents and images sent via WhatsApp using multimodal vision.
---

# Document Reader Skill

## Purpose
Process media and documents sent by Gilang or Bunga, extract key details and text layers, and ensure information is accessible for future recall.

## Processing Playbook
1. **Multimodal Analysis**: Extract readable text, numbers, dates, line items, and visual semantics from attached images, scans, and PDFs.
2. **Key Data Extraction**: Identify structured anchors (e.g. invoice amounts, payment due dates, account numbers, flight times, policy numbers).
3. **Storage**: Save documents and extracted facts using the Document Vault and semantic memory.
4. **Delivery**: Present extracted information clearly using native WhatsApp formatting (`*bold*` for headers and keys, `_italics_` for secondary metadata). Never use decorative emojis or boilerplate assistant closings.

## Querying Past Documents
- When users ask about details from past receipts, bills, or PDFs, search the vault using `search_vault_files` or `read_vault_file`.
- Ground responses strictly in the stored document facts.
