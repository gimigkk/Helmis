# Scenarios & Operational Playbooks

This document outlines real-world interaction scenarios, conversational edge cases, and operational playbooks for Helmis.

---

## 1. Task Management & Rescheduling Scenarios

### Scenario A: Explicit Task Creation with Lead-Time Buffer
- **Inbound Message**: `[Gilang]: Besok jam 18:30 ada meeting dengan Pak Budi di Kuningan, ingetin ya`
- **ReAct Execution**:
  1. Identifies academic/work meeting intent.
  2. Calculates `lead_time_minutes=30` (heads-up buffer at 18:00 WIB).
  3. Executes `add_task(title="Meeting dengan Pak Budi di Kuningan", assignee="Gilang", due_date="YYYY-MM-DD", due_time="18:30", lead_time_minutes=30)`.
- **Response**:
  ```text
  Siap, reminder *Meeting dengan Pak Budi di Kuningan* sudah dicatat untuk besok pukul 18:30 WIB (pengingat persiapan 18:00 WIB).
  ↳ `add_task`
  ```

### Scenario B: Dynamic Mid-Turn Steering
- **Turn Event**: User sends `[Gilang]: Catat tugas analgor besok jam 8`.
- **Mid-Turn Follow-Up**: While the agent is executing `add_task`, user sends `[Gilang]: Eh ralat, jam 10 pagi maksudnya`.
- **ReAct Execution**:
  1. Receives mid-turn steering injection from mailbox.
  2. Adjusts target due time to `10:00` without creating duplicate tasks.
  3. Executes `add_task` or updates task record.
- **Response**:
  ```text
  Sip, dicatat untuk jam 10:00 WIB ya.
  ↳ `add_task`
  ```

---

## 2. Document Vault & Multimodal Scenarios

### Scenario A: Preserving Original Uploaded PDF Filename
- **Inbound Message**: `[Bunga sends file "P2_Gilang_M0403241117_02.pdf"]: Tolong simpenin ya`
- **ReAct Execution**:
  1. Inspects attachment metadata -> original filename `P2_Gilang_M0403241117_02.pdf`.
  2. Preserves exact filename verbatim (no synthetic slugs).
  3. Executes `save_vault_file(filename="P2_Gilang_M0403241117_02.pdf", category="documents", owner="Gilang")`.
- **Response**:
  ```text
  Sip Bunga, file *P2_Gilang_M0403241117_02.pdf* sudah disimpan di kategori documents.
  ↳ `save_vault_file`
  ```

### Scenario B: Text Inspection & Zero Hallucination
- **Inbound Message**: `[Gilang]: Isi file brief_project.txt apa ya?`
- **ReAct Execution**:
  1. Executes `read_vault_file(file_id_or_name="brief_project.txt")`.
  2. Reads digital text layers directly.
  3. Summarizes key findings accurately from the returned text.
- **Response**:
  ```text
  > *Ringkasan brief_project.txt*
  Proyek ini mencakup pengembangan sistem inventaris dengan batas waktu akhir bulan ini.
  ↳ `read_vault_file`
  ```

---

## 3. Group Chat & Conversational Non-Intervention

### Scenario A: Casual Human-to-Human Dialogue
- **Inbound Message in Trio Group**: `[Gilang to Bunga]: Sayang besok mau makan siang di mana?`
- **Follow-up**: `[Bunga]: Di tempat biasa aja yuk`
- **ReAct Execution**:
  1. Detects human-to-human pronoun usage (*"Sayang"*, *"yuk"*).
  2. Evaluates that neither user addressed Helmis nor gave a secretary command.
  3. Outputs `[NO_REPLY]`.
- **Outcome**: The agent stays completely silent with zero message dispatch.

### Scenario B: Shared Couple Task Synchronization
- **Inbound Message in Trio Group**: `[Gilang]: Mis, catet agenda kita besok jam 4 sore bayar tagihan listrik`
- **ReAct Execution**:
  1. Detects shared couple intent (*"agenda kita"*).
  2. Assigns task to `"Both"`.
  3. Executes `add_task(title="Bayar tagihan listrik", assignee="Both", due_time="16:00")`.
- **Response**:
  ```text
  Sip, agenda bersama *Bayar tagihan listrik* sudah dicatat untuk kalian berdua besok pukul 16:00 WIB.
  ↳ `add_task`
  ```
