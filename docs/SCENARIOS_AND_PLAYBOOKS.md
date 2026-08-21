# Executive Scenarios & Thinking-Out-Loud Playbook

This document is the master operational catalog of **50+ verified real-world scenarios** for Helmis, detailing the exact multi-step ReAct orchestration, intermediate status update triggers ("thinking out loud"), cross-party messaging, and state mutations across private DMs and the Trio group chat.

---

## 1. The 6 Universal Architectural Primitives

Every scenario in this catalog is executed using a combination of six core architectural primitives:

```
                      Incoming Events (Text, VN, Images, PDFs, Cron)
                                         │
                                         ▼
                 ┌───────────────────────────────────────────────┐
                 │ 1. Per-Chat Debounce Queue & Session Router   │
                 │    - 1.0s burst typing & media merger         │
                 │    - Concurrent multi-chat isolation (DM/Grp) │
                 └───────────────────────┬───────────────────────┘
                                         │
                                         ▼
                 ┌───────────────────────────────────────────────┐
                 │ 2. Native Multimodal Engine (Clean Parts)     │
                 │    - 2-Phase Voice Note Transcription         │
                 │    - Direct Vision/OCR without fake prompts   │
                 └───────────────────────┬───────────────────────┘
                                         │
                                         ▼
                 ┌───────────────────────────────────────────────┐
                 │ 3. Autonomous ReAct Loop with Active Tooling  │
                 │    - send_status_update (Thinking Out Loud)   │
                 │    - send_whatsapp_message (Cross-Party)      │
                 │    - Chained multi-tool task mutations        │
                 └───────────────────────┬───────────────────────┘
                                         │
                         ┌───────────────┴───────────────┐
                         ▼                               ▼
     ┌───────────────────────────────────────┐ ┌───────────────────────────────────────┐
     │ 4. Semantic Long-Term Vector Memory   │ │ 5. Atomic State Fidelity Guardrail    │
     │    - 3072-dim embeddings for habits   │ │    - Zero sycophancy or false claims  │
     │    - Passive background extraction    │ │    - Atomic POSIX file locks          │
     └───────────────────────────────────────┘ └───────────────────────────────────────┘
                                         │
                                         ▼
                 ┌───────────────────────────────────────────────┐
                 │ 6. Proactive Background Scheduler (Cron)      │
                 │    - Deadline evaluation & WhatsApp pings     │
                 │    - Escalation ladders & snoozing            │
                 └───────────────────────────────────────────────┘
```

---

## 2. Thinking-Out-Loud & Messaging Decision Matrix

To ensure Helmis communicates like a competent human secretary without generating notification spam, intermediate messages follow a strict decision matrix:

| Scenario Type | Action | Tool Invoked | WhatsApp Behavior |
| :--- | :--- | :--- | :--- |
| **Instant Local Queries** (*"Ada task apa?"*, *"Catat beli susu"*) | Execute silently $\rightarrow$ deliver final response | None (direct tool) | **1 clean final message** (0 intermediate buzzes) |
| **Heavy Multi-Step Research & Comparison** (*"Bandingkan 3 venue di Bogor"*) | Acknowledge plan $\rightarrow$ research $\rightarrow$ synthesize | `send_status_update` | **1 status update + 1 final detailed report** |
| **Cross-Party Relay / Delegation** (*"Tolong kasih tau Bunga X"*) | Notify 3rd party $\rightarrow$ update database $\rightarrow$ confirm to sender | `send_whatsapp_message(to="Bunga")` | **1 message to Bunga + 1 final confirmation to sender** |
| **Group Announcements from DM** (*"Umumkan di grup Trio"*) | Post in group $\rightarrow$ store task $\rightarrow$ confirm | `send_whatsapp_message(to="group")` | **1 post in Trio Group + 1 confirmation in DM** |
| **Destructive Action Verification** (*"Hapus semua task"*) | Check count $\rightarrow$ prompt confirmation | None (query only) | **1 clarification prompt (zero premature deletes)** |

---

## 3. The 50 Scenarios Catalog

### Category A: Cross-Party Relay & Delegation (DM $\leftrightarrow$ Group)

#### 1. Relay Information to Partner with Local Reminder
* **User (Gilang DM)**: *"Tolong kasih tau Bunga kalau aku lagi di jalan dan bakal telat 15 menit, terus ingetin aku buat telpon dia pas sampe."*
* **ReAct Steps**:
  1. `send_whatsapp_message(recipient="Bunga", text="Hai Bunga, Gilang menginfokan bahwa dia sedang di jalan dan kemungkinan terlambat sekitar 15 menit ya.")`
  2. `add_task(title="Telpon Bunga setelah sampai", due="Hari ini 19:30 WIB", assignee="Gilang")`
* **Final Response to Gilang**: *"Siap Gilang, sudah saya kabari Bunga dan task untuk telpon Bunga sudah dicatat."*

#### 2. Cross-Party Schedule Query
* **User (Gilang DM)**: *"Helmis, Bunga punya jadwal ngajar les hari apa aja minggu ini?"*
* **ReAct Steps**:
  1. `list_tasks(status="pending", assignee="Bunga")`
* **Final Response to Gilang**: *"Bunga ada agenda les pada hari Jumat pukul 10:00 WIB (*Nge-chat anak murid buat les*)."*

#### 3. Group Announcement from Private DM
* **User (Bunga DM)**: *"Helmis, tolong umumkan di grup Trio kalau kita perlu finalize budget jualan preloved besok malam."*
* **ReAct Steps**:
  1. `send_whatsapp_message(recipient="group", text="Pengumuman untuk Gilang & Bunga: budget jualan preloved perlu kita finalize besok malam ya.")`
  2. `add_task(title="Finalize budget jualan preloved", due="2026-08-29 20:00 WIB", assignee="Semua")`
* **Final Response to Bunga**: *"Pengumuman sudah saya kirim ke grup Trio dan task sudah dicatat untuk besok malam."*

#### 4. Shared Contact Retrieval in Group
* **User (Gilang in Group)**: *"Helmis, nomor kontak Pak RT berapa ya? Bunga yang nyimpan."*
* **ReAct Steps**:
  1. `search_notes(query="Pak RT")`
* **Final Response in Group**: *"Berikut kontak Pak RT: 0812-xxxx-xxxx."*

---

### Category B: Multi-Step & Complex Workflow Handling

#### 5. Multi-Document Invoice & Task Extraction
* **User (Gilang DM)**: *(Sends PDF/Image invoice)* *"Tolong rekap tagihan ini, masukin deadline pembayarannya ke task, terus ingetin Bunga juga."*
* **ReAct Steps**:
  1. `send_status_update(text="Sedang membaca invoice dan merekap rinciannya ya...")`
  2. OCR extracts: PT Kriyamic, Total Rp 4.500.000, Jatuh Tempo: 30 Agustus 2026.
  3. `add_task(title="Bayar tagihan PT Kriyamic Rp 4.500.000", due="2026-08-30 12:00 WIB", assignee="Gilang")`
  4. `send_whatsapp_message(recipient="Bunga", text="Info: Tagihan PT Kriyamic sebesar Rp 4.500.000 jatuh tempo tanggal 30 Agustus 2026 (di-handle Gilang).")`
* **Final Response to Gilang**: *"Invoice PT Kriyamic sebesar *Rp 4.500.000* berhasil direkap. Task jatuh tempo *30 Agustus 2026* sudah dicatat dan Bunga sudah diinfokan."*

#### 6. Deep Research & Venue Comparison
* **User (Gilang DM)**: *"Helmis, coba bandingkan 3 opsi venue meeting untuk Asah di Bogor beserta harganya."*
* **ReAct Steps**:
  1. `send_status_update(text="Siap Gilang, saya kumpulkan perbandingan 3 venue di Bogor terlebih dahulu ya...")`
  2. Search / memory synthesis.
* **Final Response**: Detailed markdown comparison table with capacity, pricing, and pros/cons.

#### 7. Cascading Schedule Rescheduling
* **User (Bunga in Group)**: *"Meeting Kriyamic tanggal 30 diundur jadi tanggal 31 jam 14:00 ya."*
* **ReAct Steps**:
  1. `update_task(title="Membuat zoom schedule untuk Kriyamic", due="2026-08-31 14:00 WIB")`
* **Final Response in Group**: *"Jadwal meeting Kriyamic sudah diupdate ke *Senin, 31 Agustus 2026 pukul 14:00 WIB*."*

---

### Category C: Ambiguity, Clarification & Safety Guardrails

#### 8. Ambiguous Assignee Disambiguation
* **User (Gilang in Group)**: *"Ingetin besok beli kue tart ya."*
* **ReAct Steps**:
  1. `search_memories(query="anniversary / kue")` $\rightarrow$ Resolves anniversary context.
  2. `add_task(title="Beli kue tart", due="Besok 10:00 WIB", assignee="Gilang")`
* **Final Response**: *"Sip Gilang, task beli kue tart besok sudah dicatat."*

#### 9. Missing Data Prompting
* **User (Gilang DM)**: *"Tolong masukin task meeting sama klien kemarin."*
* **ReAct Steps**:
  1. `search_notes(query="klien")` $\rightarrow$ Finds multiple clients.
* **Final Response**: *"Bisa tolong sebutkan nama klien dan jam meeting yang diinginkan?"*

#### 10. Destructive Action Safeguard
* **User (Bunga DM)**: *"Hapus semua task!"*
* **ReAct Steps**:
  1. `list_tasks(status="pending")` $\rightarrow$ 6 tasks found.
* **Final Response**: *"Saat ini ada 6 task aktif di database. Apakah kamu yakin ingin menghapus semuanya atau hanya task tertentu?"*

---

### Category D: Zero-Chatter Instant Actions (< 2s)

#### 11. Quick Task Listing
* **User**: *"Ada task apa aja hari ini?"*
* **ReAct Steps**: `list_tasks(status="pending")`
* **Final Response**: Instant formatted task list. (0 intermediate status updates).

#### 12. Quick Note Taking
* **User**: *"Catat: Ukuran baju kemeja Gilang L, celana 32."*
* **ReAct Steps**: `save_note(title="Ukuran Pakaian Gilang", content="Kemeja: L, Celana: 32")`
* **Final Response**: *"Catatan ukuran pakaian Gilang sudah disimpan."*

#### 13. Passive Memory Retrieval
* **User**: *"Kapan anniversary kita?"*
* **ReAct Steps**: `search_memories(query="anniversary")`
* **Final Response**: *"Anniversary kalian adalah hari Jumat, 28 Agustus 2026."*

#### 14. Casual Banter & Reaction Stickers
* **User**: *(Sends playful kitten sticker `:P`)*
* **ReAct Steps**: Multimodal recognition.
* **Final Response**: Short playful banter or `[NO_REPLY]` if in group. (Never describe the image).

---

### Category E: Proactive & External Coordination

#### 15. Proactive Deadline Warning
* **Trigger**: Supercronic tick at 14:30 WIB; Task due at 15:00 WIB.
* **ReAct Steps**: `send_whatsapp_message(recipient="Gilang", text="Pengingat: *ILT Personal Productivity Asah* dijadwalkan hari ini pukul 15:00 WIB (30 menit lagi).")`

#### 16. Partner Status Follow-up
* **User (Gilang DM)**: *"Bunga udah ngerjain tugas ekonomi syariahnya belum ya?"*
* **ReAct Steps**: `list_tasks(assignee="Bunga")`
* **Final Response**: *"Tugas ekonomi syariah Bunga saat ini masih berstatus pending."*

#### 17. Batch Voice Note Extraction
* **User (Bunga DM)**: *(Sends 45s Voice Note with 3 items)*
* **ReAct Steps**:
  1. `send_status_update(text="Sedang mendengarkan pesan suara dan mencatat agendanya...")`
  2. Transcribes VN $\rightarrow$ extracts 3 tasks.
  3. `add_task` $\times 3$.
* **Final Response**: Formatted list of all 3 tasks created.

#### 18. Schedule Conflict Detection
* **User (Gilang DM)**: *"Jadwalkan meeting Kriyamic besok jam 3 sore."*
* **ReAct Steps**:
  1. `list_tasks` $\rightarrow$ Detects *ILT Asah* already at 15:00 WIB.
  2. `add_task(title="Meeting Kriyamic", due="Besok 15:00 WIB", assignee="Gilang")`
* **Final Response**: *"Task *Meeting Kriyamic* berhasil dicatat besok pukul 15:00 WIB. Perhatian: ada jadwal *ILT Asah* di jam yang sama."*

#### 19. Contact Lookup & Message Proposal
* **User**: *"Kontak murid les yang namanya Rian ada?"*
* **ReAct Steps**: `search_notes(query="Rian")`
* **Final Response**: *"Kontak Rian: 0813-xxxx-xxxx. Apakah kamu mau saya kirimkan pesan ke Rian?"*

#### 20. Conversation Silence Compliance
* **User**: *"Oke Helmis makasih, udah beres kok."*
* **Final Response**: `[NO_REPLY]` (Turn closes silently).

---

### Category F: Privacy Boundaries & Cross-Channel Security

#### 21. DM Privacy Leak Prevention in Group Chat
* **Context**: Gilang planned a surprise in DM. Bunga asks in Group: *"Gilang beli kado apa?"*
* **Final Response in Group**: *"Untuk rincian pengeluaran personal Gilang, silakan konfirmasi langsung ke Gilang ya."*

#### 22. Group Human-to-Human Banter Non-Interference
* **Context**: Gilang & Bunga chat with each other in Group without summoning Helmis.
* **Final Response**: `[NO_REPLY]`.

#### 23. Direct Address in Group Chat
* **Context**: *"Helmis, tolong catat daftar belanjaan tadi ya."*
* **Final Response**: Executes tool and confirms directly in group.

---

### Category G: Multi-Media & Rapid Burst Typing

#### 24. Image + Follow-up Voice Note in Rapid Succession
* **Context**: User sends bill photo, then 1 second later sends VN: *"Bagi dua sama Bunga ya"*.
* **ReAct Steps**: Debouncer merges into 1 turn $\rightarrow$ transcribes $\rightarrow$ splits bill $\rightarrow$ creates task.

#### 25. Silent or Corrupted Voice Note
* **Final Response**: `> "(Audio tidak terdengar jelas)"` *"Maaf, pesan suara tidak terdengar jelas karena suara latar. Bisa tolong ketik atau kirim ulang?"*

#### 26. Screenshot of Chat / Social Media
* **ReAct Steps**: Extracts text from screenshot $\rightarrow$ asks if actionable items should be scheduled.

---

### Category H: Temporal & WIB Boundaries

#### 27. Midnight Boundary Rollover (23:55 WIB)
* **User at 23:55 WIB**: *"Ingetin besok jam 8 pagi ada call."*
* **Behavior**: Accurately resolves to Wednesday morning (in 8 hours), not Thursday.

#### 28. Relative Indonesian Words ("Lusa", "Akhir Bulan")
* **User**: *"Lusa sore ingetin ngoreksi tugas les."*
* **Behavior**: Accurately maps "lusa sore" to +2 days at 16:00 WIB.

#### 29. Elapsed Deadline Warning
* **User at 20:00 WIB**: *"Ingetin tadi sore jam 4 beli kopi."*
* **Behavior**: Detects elapsed time and proposes tomorrow at 16:00 WIB.

---

### Category I: Failure Recovery & Tool Degradation

#### 30. External Contact Messaging Failure
* **Behavior**: Tool returns `status: "error"` $\rightarrow$ Agent explains WhatsApp connectivity failure honestly.

#### 31. Duplicate Task Prevention
* **Behavior**: Detects existing pending task with same name $\rightarrow$ notifies user without creating duplicate.

#### 32. Zero Search Matches
* **Behavior**: Returns honest "not found" message without hallucinating records.

---

### Category J: Relationship & Identity Graph

#### 33. Alias Resolution ("Mama", "Adik")
* **Behavior**: Resolves "Mama" $\rightarrow$ "Ibu Bunga" and stores structured fact.

#### 34. Multi-Task Batch Completion
* **Behavior**: Loops through and completes all matching tasks by project keyword.

#### 35. Emergency Interrupt ("BATALKAN SEMUA")
* **Behavior**: Cancels all today's scheduled meetings immediately.

---

### Category K: Shared Finances, Split Bills & Subscriptions

#### 36. Complex Multi-Item Shared Expense Tracking
* **Context**: Supermarket receipt with shared groceries + 1 personal item.
* **Behavior**: Calculates personal deduction, splits balance 50/50, and creates reimbursement task.

#### 37. Recurring Subscription Renewal
* **Behavior**: Stores monthly renewal rule (Canva Pro, 5th of each month) and schedules warning.

#### 38. Price Research Comparison
* **Behavior**: Returns structured service pricing breakdown (AC servicing in Bogor).

---

### Category L: Health, Routines & Dietary Preferences

#### 39. Medication Routine Pairing
* **Behavior**: Generates 12-hour recurring reminders (08:00 & 20:00 WIB) for 5-day antibiotic course.

#### 40. Passive Dietary Conflict Alert
* **Behavior**: Warns about partner's seafood allergy when selecting restaurant.

---

### Category M: Travel Logistics & Itineraries

#### 41. Flight Booking Extraction
* **Behavior**: OCR extracts e-ticket details, schedules flight task + 3-hour prior airport departure task.

#### 42. Dynamic Shared Packing Checklist
* **Behavior**: Creates structured note checklist with item additions supported.

---

### Category N: Slang, Jargon & Dialects

#### 43. Informal Indonesian / Slang Parsing
* **Behavior**: Understands *"bsk pg bgt jam 6an ingetin gw kudu otw ke stasiun"*.

#### 44. Mixed English & Indonesian Tech Jargon
* **Behavior**: Understands *"push code ke repo Hermes udah merged, sync env var di VPS besok sore"*.

---

### Category O: Partner Negotiation & Availability

#### 45. Calendar Availability Matchmaker
* **Behavior**: Cross-references Gilang & Bunga schedules and suggests mutually free cinema slots.

#### 46. Task Hand-off Between Partners
* **Behavior**: Reassigns task owner from Gilang to Bunga upon mutual agreement in group.

---

### Category P: Interactive Snooze & Escalation

#### 47. Interactive Reminder Snooze
* **User**: *"Snooze 2 jam lagi ya, lagi nyetir."*
* **Behavior**: Re-evaluates due time to `now + 2h`.

#### 48. Overdue Escalation to Partner
* **Behavior**: Follows up with partner if critical task remains unconfirmed.

---

### Category Q: Quiet Mode & Rapid Corrections

#### 49. Late Night Non-Urgent Batching (Quiet Hours)
* **Behavior**: Automatically shifts 01:30 AM non-urgent reminder to 08:00 AM.

#### 50. Voice Note Cancellation via Rapid Text
* **Behavior**: Debouncer merges VN + instant cancellation text $\rightarrow$ drops VN action items.
