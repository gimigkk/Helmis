---
name: vault-manager
description: Clean Document Vault, File Storage Hierarchy, Metadata Catalog, Search, Text Inspection, and WhatsApp Dispatching.
---

# Vault Manager Skill

This skill governs how Helmis manages binary files, scans, PDFs, images, receipts, and documents in the **Document Vault** (`./data/vault/`).

---

## 1. Vault Directory Hierarchy & Cleanliness

Files are organized in clean, structured categories:

```
data/vault/
├── health/         # BPJS, medical records, doctor prescriptions, MCU lab results
│   ├── gilang/
│   ├── bunga/
│   └── shared/
├── id_cards/       # KTP, SIM, NPWP, Paspor, Kartu Keluarga, Akta
│   ├── gilang/
│   ├── bunga/
│   └── shared/
├── travel/         # Flight e-tickets, hotel vouchers, train tickets, visas
│   ├── gilang/
│   ├── bunga/
│   └── shared/
├── receipts/       # Proof of payment, invoices, bills, warranty cards, tax BPE
│   ├── gilang/
│   ├── bunga/
│   └── shared/
├── documents/      # CV, work contracts, NDA, degree diplomas, tutoring modules
│   ├── gilang/
│   ├── bunga/
│   └── shared/
├── media/          # Saved media photos, videos, audio clips
│   ├── gilang/
│   ├── bunga/
│   └── shared/
└── projects/       # Custom project workspaces (e.g. freelance_webdev, kriyamic)
```

---

## 2. Ingestion Playbook (Saving Files)

When a user sends a media document/photo with an archiving intent (*"Mis, simpenin scan BPJS gw"*, *"Ini bukti transfer 350rb"*):
1. Determine appropriate **category**: `health`, `id_cards`, `travel`, `receipts`, `documents`, `media`, or custom `subfolder`.
2. Determine **owner**: `"Gilang"`, `"Bunga"`, or `"Both"`/`"Shared"`.
3. Format clean, descriptive slug filename (e.g., `scan_bpjs_kesehatan_gilang.pdf`, `e-ticket_garuda_bali.pdf`).
4. Call `save_vault_file(filename=..., category=..., owner=..., tags=[...], description=...)`. The actual raw binary media is automatically preserved.
5. Confirm politely in zero-emoji executive secretary tone.

---

## 3. Reading & Content Inspection Playbook

When a user asks about the contents or details inside a stored file (*"Isi file brief_project.txt apa?"*, *"Di brosur Elera biaya les kelas 6 berapa?"*, *"Bacain ringkasan polis di asuransi.pdf"*):
1. Call `read_vault_file(file_id_or_name=...)`.
2. For PDFs, `pypdf` extracts all digital text layers across pages. For text/code/markdown, full text is decoded. For images, OCR summaries are returned.
3. Answer the user's question directly from the extracted content.

---

## 4. Retrieval & Dispatching Playbook (Sending Files)

When a user asks for a file (*"Lu punya file scan bpjs gw ga? Kirim dong"*, *"Kirim tiket pesawat kita"*):
1. Call `search_vault_files(query=..., owner=...)`.
2. If match found, call `send_vault_file(file_id_or_name=..., recipient=..., caption=...)`.
3. If multiple ambiguous matches found, list them cleanly and ask the user to clarify.

---

## 5. File Operations & Directory Organization

1. **Creating Custom Directories**:
   * Use `create_vault_directory(directory_path="projects/kriyamic")`.
2. **Dynamic Move (Single or Bulk)**:
   * Use `move_vault_files(target="kriyamic", destination_directory="projects/kriyamic")` or `move_vault_files(target="doc_123", new_owner="Both")`.
3. **Dynamic Delete (Single or Bulk)**:
   * Use `delete_vault_files(target="doc_123")` or `delete_vault_files(target="temp_draft")`.
4. **Deleting Directories Safely**:
   * Use `delete_vault_directory(directory_path="...", recursive=True)`. Default core categories are strictly protected.
