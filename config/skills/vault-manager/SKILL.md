---
name: vault-manager
description: Manage document vault, file storage hierarchy, metadata catalog, search, text inspection, and WhatsApp file dispatching.
---

# Vault Manager Skill

## Purpose
Manage binary files, document scans, PDFs, receipts, and images in the Document Vault (`./data/vault/`).

---

## 1. Vault Directory Hierarchy
Files are organized by category and owner:
- `health`: Medical records, prescriptions, lab results, insurance documents.
- `id_cards`: Identity cards, passports, driver licenses, family cards.
- `travel`: Boarding passes, flight tickets, hotel bookings, itineraries.
- `receipts`: Payment proofs, invoices, bills, warranties, tax documents.
- `documents`: Contracts, CVs, agreements, academic documents, modules.
- `media`: Photos, videos, audio clips.
- `projects`: Workspace directories for custom projects.

---

## 2. Ingestion & Storage Rules
1. **Category & Owner**: Identify the logical category and owner (`"Gilang"`, `"Bunga"`, or `"Both"`).
2. **Filename Invariants**:
   - **Named Files**: Preserve the user's original uploaded filename verbatim.
   - **Generic / Unnamed Media**: If the uploaded item has a generic camera filename (e.g. `IMG-...`, `image.jpeg`, `document.pdf`), formulate a descriptive slug based on its visual content.
   - **Explicit User Rename**: If the user explicitly asks to name the file something specific, use the requested name.
3. **Execution**: Call `save_vault_file(filename=..., category=..., owner=..., tags=[...], description=...)`. Confirm briefly in authentic WhatsApp secretary tone.

---

## 3. Inspection & Question Answering
1. When asked about the content, line items, or metadata of a file, invoke `search_vault_files` or `read_vault_file` first.
2. Ground all answers strictly on the extracted text or OCR summary returned by the tool.
3. If a queried file does not exist, state clearly that it is not found.

---

## 4. Retrieval & Dispatching
1. When asked to retrieve or send a document, search for the target file via `search_vault_files`.
2. Dispatch the file using `send_vault_file(file_id_or_name=..., recipient="current")`. Always send directly to the active chat where the request occurred (Group or DM). Never redirect to a private DM unless explicitly asked.
3. If multiple ambiguous matches exist, list the matching candidates and ask for clarification.

---

## 5. File Operations
- **Directory Creation**: `create_vault_directory(directory_path=...)`
- **Moving Files**: `move_vault_files(target=..., destination_directory=..., new_owner=...)`
- **Deleting Files**: `delete_vault_files(target=...)`
- **Deleting Directories**: `delete_vault_directory(directory_path=..., recursive=...)`
