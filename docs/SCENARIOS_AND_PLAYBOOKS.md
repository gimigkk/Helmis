# Master Catalog: 50 Real-World Executive Scenarios & Playbooks

Master operational reference of **50 verified real-world scenarios** for Helmis, detailing multi-step ReAct orchestration, 2-stage preparation buffers, urgent nag escalation ladders, conversational snoozing, Document Vault file retrieval, and couple synchronization across private DMs and the Trio group chat.

---

## Index of Categories

- [Category A: 2-Stage Lead-Time Buffers & Preparation (1–10)](#category-a-2-stage-lead-time-buffers--preparation)
- [Category B: Urgent 10-Minute Nag Loops & Partner Escalations (11–18)](#category-b-urgent-10-minute-nag-loops--partner-escalations)
- [Category C: Conversational Fluidity: Snooze, Reschedule & Early Done (19–25)](#category-c-conversational-fluidity-snooze-reschedule--early-done)
- [Category D: Document Vault & Clean File Management (26–33)](#category-d-document-vault--clean-file-management)
- [Category E: Shared Couple Tasks & Trio Group Synchronization (34–40)](#category-e-shared-couple-tasks--trio-group-synchronization)
- [Category F: Multimodal Intelligence: Voice Notes, Video & OCR (41–46)](#category-f-multimodal-intelligence-voice-notes-video--ocr)
- [Category G: Cross-Party Relays & Executive Secretarial Workflows (47–50)](#category-g-cross-party-relays--executive-secretarial-workflows)

---

## Category A: 2-Stage Lead-Time Buffers & Preparation

Tasks requiring focused preparation receive an automated **Stage 1 (Kickoff Buffer)** at $T - \text{Lead Time}$ followed by a **Stage 2 (Final Cutoff)** at the actual deadline.

### 1. Academic University Assignment
* **User (Bunga DM)**: *"Mis, ingetin deadline tugas Ekonomi Syariah hari ini jam 20:30 WIB ya."*
* **Helmis Execution**: Infers `lead_time_minutes=120` (2 hours prep buffer) & `priority="normal"`.
* **Stage 1 (18:30 WIB)**: *"Halo Bunga, pengingat persiapan: deadline *Tugas Ekonomi Syariah* pada 20:30 WIB (sisa 2 jam lagi). Waktunya mulai persiapan atau pengerjaan ya."*
* **Stage 2 (20:30 WIB)**: *"Halo Bunga, pengingat deadline: *Tugas Ekonomi Syariah* (20:30 WIB). Jika sudah selesai disubmit, kabari Helmis ya."*

### 2. Work Pitch Deck Proposal
* **User (Gilang DM)**: *"Catat submit proposal hibah ke investor besok jam 17:00 WIB."*
* **Helmis Execution**: Infers `lead_time_minutes=90` (1.5 hours prep buffer) & `priority="normal"`.
* **Stage 1 (Tomorrow 15:30 WIB)**: *"Halo Gilang, pengingat persiapan: deadline *Submit proposal hibah ke investor* besok 17:00 WIB (sisa 1 jam 30 menit lagi)."*
* **Stage 2 (Tomorrow 17:00 WIB)**: *"Halo Gilang, pengingat deadline: *Submit proposal hibah ke investor* (17:00 WIB). Apakah sudah terkirim?"*

### 3. Flight Departure & Airport Arrival
* **User (Gilang DM)**: *"Mis, flight Garuda ke Bali Jumat jam 14:00 WIB."*
* **Helmis Execution**: Infers `lead_time_minutes=180` (3 hours buffer) & `priority="urgent"`.
* **Stage 1 (Friday 11:00 WIB)**: *"Halo Gilang, pengingat persiapan: jadwal flight *Garuda ke Bali* jam 14:00 WIB (sisa 3 jam lagi). Waktunya jalan ke bandara untuk check-in & bagasi."*
* **Stage 2 (Friday 14:00 WIB)**: *"Halo Gilang, pengingat deadline: *Garuda ke Bali* (14:00 WIB). Boarding gate sudah masuk?"*

### 4. Client Zoom Presentation
* **User (Gilang DM)**: *"Ingetin besok ada Zoom meeting sama klien jam 10 pagi."*
* **Helmis Execution**: Infers `lead_time_minutes=30` (30 mins buffer) & `priority="normal"`.
* **Stage 1 (Tomorrow 09:30 WIB)**: *"Halo Gilang, pengingat persiapan: *Zoom meeting sama klien* jam 10:00 WIB (sisa 30 menit lagi). Waktunya siapkan deck & mic."*
* **Stage 2 (Tomorrow 10:00 WIB)**: *"Halo Gilang, pengingat deadline: *Zoom meeting sama klien* dimulai sekarang."*

### 5. Medical Doctor / Dentist Appointment
* **User (Bunga DM)**: *"Jadwal dokter gigi hari Sabtu jam 15:00 WIB di Senopati."*
* **Helmis Execution**: Infers `lead_time_minutes=60` (1 hour travel buffer).
* **Stage 1 (Saturday 14:00 WIB)**: *"Halo Bunga, pengingat persiapan: *Jadwal dokter gigi di Senopati* jam 15:00 WIB (sisa 1 jam lagi). Waktunya jalan ya."*
* **Stage 2 (Saturday 15:00 WIB)**: *"Halo Bunga, pengingat jadwal: *Dokter gigi di Senopati* (15:00 WIB)."*

### 6. Thesis Chapter Review
* **User (Bunga DM)**: *"Deadline revisi bab 4 skripsi lusa jam 16:00 WIB."*
* **Helmis Execution**: Infers `lead_time_minutes=120` (2 hours buffer).
* **Stage 1 (Lusa 14:00 WIB)**: *"Halo Bunga, pengingat persiapan: *Revisi bab 4 skripsi* lusa 16:00 WIB (sisa 2 jam lagi)."*

### 7. Pre-Event Soundcheck
* **User (Gilang DM)**: *"Soundcheck event Kriyamic hari Minggu jam 13:00 WIB."*
* **Helmis Execution**: Infers `lead_time_minutes=60` buffer.
* **Stage 1 (Sunday 12:00 WIB)**: *"Halo Gilang, pengingat persiapan: *Soundcheck event Kriyamic* jam 13:00 WIB (sisa 1 jam lagi)."*

### 8. Web Development Production Release
* **User (Gilang DM)**: *"Deploy update v2 ke server nanti malam jam 23:00 WIB."*
* **Helmis Execution**: Infers `lead_time_minutes=60` staging prep buffer.
* **Stage 1 (22:00 WIB)**: *"Halo Gilang, pengingat persiapan: *Deploy update v2* jam 23:00 WIB (sisa 1 jam lagi). Pastikan staging build sudah green."*

### 9. Private Tutoring Lesson Prep
* **User (Bunga DM)**: *"Ngajar les matematika anak murid besok jam 16:00 WIB."*
* **Helmis Execution**: Infers `lead_time_minutes=30` buffer.
* **Stage 1 (Tomorrow 15:30 WIB)**: *"Halo Bunga, pengingat persiapan: *Ngajar les matematika* jam 16:00 WIB (sisa 30 menit lagi). Siapkan modul & worksheet."*

### 10. Explicit 0-Lead Instant Errand
* **User (Gilang DM)**: *"Ingetin transfer uang kosan hari ini jam 12:00 WIB, pas jamnya aja ga usah dari pagi."*
* **Helmis Execution**: Sets `lead_time_minutes=0` explicitly.
* **Stage 1**: Skipped.
* **Stage 2 (12:00 WIB)**: *"Halo Gilang, pengingat deadline: *Transfer uang kosan* (12:00 WIB)."*

---

## Category B: Urgent 10-Minute Nag Loops & Partner Escalations

For life-critical / high-stakes tasks (`priority="urgent"`), Helmis triggers an automated **10-minute follow-up loop** until acknowledged, escalating to the partner at 30 minutes and standing down at 60 minutes.

### 11. Urgent Prescription Medication
* **User (Gilang DM)**: *"Mis, ingetin minum obat antibiotik dokter jam 13:00 WIB, ini wajib jangan sampe kelewat."*
* **Helmis Setup**: Sets `priority="urgent"`, `lead_time_minutes=0`.
* **Stage 2 (13:00 WIB - Nudge #1)**: *"Halo Gilang, pengingat deadline: *Minum obat antibiotik dokter* (13:00 WIB). Jika sudah diminum, kabari Helmis ya."*
* **T+10m (13:10 WIB - Nudge #2)**: *"Gilang, tugas penting *Minum obat antibiotik dokter* belum ada konfirmasi (10 menit lalu). Apakah sudah beres atau masih berjalan?"*
* **T+20m (13:20 WIB - Nudge #3)**: *"Gilang, pengingat ke-3 untuk *Minum obat antibiotik dokter* (20 menit lewat). Mohon konfirmasi statusnya ya."*
* **T+30m (13:30 WIB - Nudge #4 & Escalation)**:
  * **To Gilang**: *"PENTING: Gilang, tugas *Minum obat antibiotik dokter* sudah 30 menit lewat dari jadwal dan belum ada konfirmasi."*
  * **Cross-Alert to Bunga**: *"PENTING: Bunga, Gilang belum ada konfirmasi untuk tugas urgent *Minum obat antibiotik dokter* (30 menit lewat). Tolong bantu cek atau bangunkan Gilang ya."*
* **T+40m (13:40 WIB - Nudge #5)**: *"PENTING: Gilang, pengingat ke-5 untuk *Minum obat antibiotik dokter* (40 menit lewat)."*
* **T+50m (13:50 WIB - Nudge #6)**: *"PENTING: Gilang, pengingat ke-6 untuk *Minum obat antibiotik dokter* (50 menit lewat)."*
* **T+60m (14:00 WIB - Stand Down)**: *"Helmis menghentikan pengingat otomatis untuk *Minum obat antibiotik dokter* (sudah 60 menit tanpa respon). Tugas tetap tercatat 'pending' di daftar tugas."*

### 12. Early Confirmation Halts Nag Loop
* **Context**: Ongoing Nag loop on Scenario 11 at 13:15 WIB.
* **User (Gilang DM)**: *"Udah gw minum barusan mis"*
* **Helmis Execution**: Calls `complete_task("Minum obat antibiotik dokter")`.
* **Helmis Reply**: *"Sip Gilang, *Minum obat antibiotik dokter* sudah ditandai selesai."* (Cancels all future nag ticks).

### 13. Stove / Cooking Hazard Safety Check
* **User (Bunga DM)**: *"Mis, ingetin matiin kompor rebusan daging jam 14:00 WIB ya, urgent."*
* **Helmis Setup**: Sets `priority="urgent"`.
* **Execution**: Nag loop ensures kitchen safety; escalates to Gilang if Bunga falls asleep after 30 minutes.

### 14. Early Morning Flight Wake-Up
* **User (Gilang DM)**: *"Bangunin gw jam 04:00 subuh besok, ada flight pagi. Urgent."*
* **Helmis Setup**: Sets `priority="urgent"`, `due="Besok 04:00 WIB"`.
* **Execution**: Alarms Gilang at 04:00. At 04:30, alerts Bunga to physically wake Gilang up.

### 15. Real-Time Banking / Transfer Cutoff
* **User (Gilang DM)**: *"Bayar invoice vendor sebelum jam 15:00 WIB, lewat jam itu kena denda 10%."*
* **Helmis Setup**: Sets `priority="urgent"`.
* **Execution**: Nag loop ensures critical business transactions are not missed.

### 16. Fast-Expiring Concert Ticket Drop
* **User (Bunga DM)**: *"War tiket konser Coldplay jam 10:00 WIB."*
* **Helmis Setup**: `lead_time_minutes=15`, `priority="urgent"`.
* **Execution**: 09:45 Stage 1 buffer + 10:00 nag check.

### 17. Hard Government Tax Filing Cutoff
* **User (Gilang DM)**: *"Submit lapor SPT pajak hari ini jam 16:00 WIB."*
* **Helmis Setup**: `lead_time_minutes=60`, `priority="urgent"`.
* **Execution**: Stage 1 kickoff at 15:00, deadline alert at 16:00, nag loop if unconfirmed.

### 18. Shared Urgent Task Escalation in Trio Group
* **User (Gilang in Group)**: *"Mis, ingetin kita berdua bayar PBB rumah hari ini jam 14:00 WIB, urgent."*
* **Helmis Setup**: `assignee="Both"`, `priority="urgent"`.
* **T+30m Escalation**: Dispatches to Trio group: *"PENTING: Tugas bersama *Bayar PBB rumah* sudah 30 menit lewat dari jadwal dan belum ada konfirmasi dari Gilang maupun Bunga. Mohon salah satu bantu cek ya."*

---

## Category C: Conversational Fluidity: Snooze, Reschedule & Early Done

Helmis adapts to human conversational speech without requiring rigid command syntax.

### 19. Relative Minute Snooze
* **Trigger**: Helmis sends reminder at 15:00.
* **User (Gilang DM)**: *"Bentar mis, lagi nyetir. Undur 20 menit lagi ya"*
* **Helmis Action**: Calls `update_task(title="...", new_due="Hari ini, 15:20 WIB")`. Cleanly resets all reminder counters.
* **Helmis Reply**: *"Sip Gilang, *[Title]* diundur ke jam 15:20 WIB."*

### 20. Natural Period Reschedule
* **User (Bunga DM)**: *"Mis, tugas ekonomi syariah nanti malem aja abis isya ya"*
* **Helmis Action**: Calls `update_task(title="tugas ekonomi syariah", new_due="Hari ini, 19:30 WIB")`.
* **Helmis Reply**: *"Sip Bunga, *Tugas Ekonomi Syariah* dijadwalkan ulang ke malam ini jam 19:30 WIB."*

### 21. Rollover to Tomorrow Morning
* **User (Gilang DM)**: *"Capek banget, ingetin review PR besok pagi jam 9 aja"*
* **Helmis Action**: Calls `update_task(title="review PR", new_due="Besok, 09:00 WIB")`.
* **Helmis Reply**: *"Sip Gilang, *Review PR* sudah dipindahkan ke besok jam 09:00 WIB."*

### 22. Early Done Before Reminder Fires
* **Context**: Task scheduled for 20:00 WIB. User finishes at 17:30 WIB.
* **User (Bunga DM)**: *"Mis, tugas preloved udah beres ya"*
* **Helmis Action**: Calls `complete_task("preloved")`.
* **Helmis Reply**: *"Sip Bunga, *Ngisi Gform buat jualan preloved* sudah ditandai selesai."* (Cancels all upcoming 20:00 reminders).

### 23. Conversational Indonesian Time Idiom ("Setengah 4 Sore")
* **User (Gilang DM)**: *"Ingetin meeting sama Arka besok setengah 4 sore"*
* **Helmis Parsing**: Automatically parses `setengah 4 sore` $\rightarrow$ `15:30 WIB`.
* **Helmis Reply**: *"Sip Gilang, sudah dicatat: *Meeting sama Arka* besok jam 15:30 WIB."*

### 24. Day-of-Week Natural Scheduling
* **User (Bunga DM)**: *"Ingetin les privat hari Jumat jam 2 siang"*
* **Helmis Parsing**: Resolves `Jumat jam 2 siang` $\rightarrow$ Next Friday 14:00 WIB.
* **Helmis Reply**: *"Sip Bunga, sudah dicatat untuk hari Jumat jam 14:00 WIB."*

### 25. Explicit Task Reassignment
* **User (Gilang DM)**: *"Mis, tugas beli galon alihin ke Bunga ya"*
* **Helmis Action**: Calls `update_task(title="beli galon", new_assignee="Bunga")`.
* **Helmis Reply**: *"Sip Gilang, tugas *Beli galon* sekarang dialihkan ke Bunga."*

---

## Category D: Document Vault & Clean File Management

Helmis maintains a structured vault (`./data/vault/`) with metadata cataloging, semantic search, and WhatsApp file dispatching.

### 26. Ingest & Save Healthcare Document (BPJS)
* **User (Gilang sends PDF)**: *"Mis, tolong simpenin scan BPJS gw di brankas ya"*
* **Helmis Action**:
  1. Downloads PDF from WAHA.
  2. Saves to `vault/health/gilang/scan_bpjs_kesehatan_gilang.pdf`.
  3. Indexes metadata in `file_catalog.json` (`owner="Gilang"`, `category="health"`, `tags=["bpjs", "kesehatan"]`).
* **Helmis Reply**: *"Sip Gilang, file *scan_bpjs_kesehatan_gilang.pdf* sudah disimpan rapi di brankas dokumen kesehatan kamu."*

### 27. Search & Retrieve Document via WhatsApp
* **User (Gilang DM)**: *"Lu punya file scan bpjs gw ga? Kirim dong"*
* **Helmis Action**:
  1. Calls `search_vault_files(query="scan bpjs", owner="Gilang")`.
  2. Finds `vault/health/gilang/scan_bpjs_kesehatan_gilang.pdf`.
  3. Calls `send_vault_file(file_id="...", caption="Ini file scan BPJS Kesehatan kamu, Gilang.")`.
* **WhatsApp Output**: Delivers the original PDF directly into the chat.

### 28. Ingest Government ID (KTP / SIM)
* **User (Bunga sends photo)**: *"Mis, ini foto KTP aku buat arsip"*
* **Helmis Action**: Saves to `vault/id_cards/bunga/ktp_bunga.jpg` and indexes OCR NIK data.
* **Helmis Reply**: *"Sip Bunga, foto KTP kamu sudah disimpan aman di brankas kartu identitas."*

### 29. Travel Ticket Retrieval for Flight Check-In
* **User (Gilang in Group)**: *"Mis, kirim file tiket pesawat Garuda kita buat Bali besok"*
* **Helmis Action**: Calls `search_vault_files("tiket garuda bali", owner="Both")` $\rightarrow$ dispatches `tiket_garuda_bali.pdf` to the Trio group.
* **Helmis Reply**: *"Ini e-ticket Garuda Indonesia untuk penerbangan ke Bali besok."*

### 30. Read Digital Text Directly from Vault PDF
* **User (Gilang DM)**: *"Cek brosur Elera di brankas dokumen, biaya les TK berapa ya?"*
* **Helmis Action**:
  1. Calls `read_vault_file(file_id_or_name="brosur_elera_education.pdf")`.
  2. Extracts digital PDF text across pages via `pypdf`.
  3. Locates fee structure: *"Biaya pendaftaran TK-SD: Rp 125.000, SPP: Rp 450.000/bln"*.
* **Helmis Reply**: *"Berdasarkan dokumen *brosur_elera_education.pdf*, biaya pendaftaran untuk jenjang TK-SD adalah Rp 125.000 dengan paket bulanan Rp 450.000."*

### 31. Browse Files by Category
* **User (Bunga DM)**: *"Ada dokumen apa aja di kategori kesehatan?"*
* **Helmis Action**: Calls `list_vault_files(category="health")`.
* **Helmis Reply**:
  ```
  Daftar dokumen kesehatan:
  1. *scan_bpjs_kesehatan_gilang.pdf* (Gilang)
  2. *kartu_asuransi_allianz_bunga.pdf* (Bunga)
  3. *hasil_lab_mcu_2026.pdf* (Gilang)
  ```

### 32. Ingest Expense / Invoice Receipt
* **User (Gilang sends receipt screenshot)**: *"Catat bukti transfer bayar servis motor 450rb"*
* **Helmis Action**: Saves image to `vault/receipts/gilang/servis_motor_450k.jpg`.

### 33. Move / Reorganize Files into Project Workspace
* **User (Gilang DM)**: *"Pindahin file brosur elera ke folder projects/freelance_webdev ya"*
* **Helmis Action**: Calls `move_vault_files(target="brosur_elera", destination_directory="projects/freelance_webdev")`.
* **Helmis Reply**: *"Sip Gilang, file *brosur_elera_education.pdf* sudah dipindahkan ke folder *projects/freelance_webdev/*."*

### 34. Clean Up / Delete Outdated Vault File
* **User (Gilang DM)**: *"Hapus draft CV versi lama yang di brankas"*
* **Helmis Action**: Calls `delete_vault_files(target="draft_cv_2025.pdf")`.
* **Helmis Reply**: *"Sip Gilang, file *draft_cv_2025.pdf* sudah dihapus dari brankas."*

---

## Category E: Shared Couple Tasks & Trio Group Synchronization

Coordinates shared responsibilities without duplicate effort or miscommunication.

### 34. Shared Apartment Rent Reminder
* **User (Gilang in Group)**: *"Mis, ingetin kita berdua bayar sewa apartemen tanggal 1 bulan depan jam 10 pagi"*
* **Helmis Action**: Calls `add_task(title="Bayar sewa apartemen", due="2026-09-01 10:00 WIB", assignee="Both")`.
* **Helmis Reply**: *"Sip Gilang, tugas bersama *Bayar sewa apartemen* sudah dicatat untuk kalian berdua pada 1 September 2026 jam 10:00 WIB."*

### 35. Mutual Task Completion (Prevent Duplicate Payment)
* **Trigger**: Shared reminder fires in Trio group for *Bayar tagihan listrik PLN*.
* **User (Bunga in Group)**: *"Udah aku bayar barusan lewat BCA"*
* **Helmis Action**: Calls `complete_task("Bayar tagihan listrik PLN")`.
* **Helmis Reply**: *"Sip Bunga! Tagihan listrik PLN sudah ditandai selesai (Gilang tidak perlu bayar lagi ya)."*

### 36. Anniversary Dinner Reservation
* **User (Gilang in Group)**: *"Catat anniversary dinner kita tanggal 28 Agustus jam 19:00 WIB di Osteria Gia"*
* **Helmis Action**: `add_task(title="Anniversary dinner di Osteria Gia", due="2026-08-28 19:00 WIB", assignee="Both", lead_time_minutes=60)`.
* **Stage 1 (28 Aug 18:00 WIB)**: *"Halo Gilang & Bunga, pengingat persiapan: *Anniversary dinner di Osteria Gia* jam 19:00 WIB (sisa 1 jam lagi). Waktunya bersiap-siap ya."*

### 37. Shared Grocery Shopping List
* **User (Bunga in Group)**: *"Mis, tambahin ke to-do bersama: beli beras, telur, dan detergen di supermarket besok sore"*
* **Helmis Action**: `add_task(title="Beli beras, telur, detergen di supermarket", due="Besok, 16:00 WIB", assignee="Both")`.

### 38. Group Banter Discretion
* **Context**: Gilang and Bunga joking in Trio group: *"Hahaha iya tadi lucu banget kucingnya"*.
* **Helmis Action**: Zero interruption. Stays 100% silent.

### 39. Direct Mention in Group
* **User (Gilang in Group)**: *"@helmis tolong list task kita minggu ini"*
* **Helmis Action**: Activates and outputs clean, sorted task list for both users.

### 40. Single-Assignee Clarification in Group
* **User (Bunga in Group)**: *"Mis, ingetin Gilang buat ganti oli Vespa besok siang ya"*
* **Helmis Action**: Assigns task to `Gilang` specifically, acknowledging in group.

---

## Category F: Multimodal Intelligence: Voice Notes, Video & OCR

Handles voice notes, video reasoning, and image OCR natively.

### 41. Hands-Free Voice Note Task Creation
* **User (Gilang sends 5s Voice Note)**: *[Audio: "Mis tolong catetin besok jam 2 siang ada meeting sama Pak Hendra di PIM"]*
* **Helmis Action**: Transcribes VN via Groq Whisper $\rightarrow$ calls `add_task("Meeting sama Pak Hendra di PIM", "Besok 14:00 WIB", lead_time_minutes=60)`.
* **Helmis Reply**: *"Sip Gilang, sudah dicatat: *Meeting sama Pak Hendra di PIM* besok jam 14:00 WIB (pengingat persiapan jam 13:00 WIB)."*

### 42. Voice Note Snooze Reply
* **Trigger**: Helmis sends reminder.
* **User (Bunga sends 3s Voice Note)**: *[Audio: "Nanti dulu ya mis, lagi makan, setengah jam lagi"]*
* **Helmis Action**: Transcribes $\rightarrow$ calls `update_task(new_due="30 menit lagi")`.

### 43. Video Analysis Without Hallucination
* **User (Gilang sends video)**: *"Ini motor apa ya?"* (Video shows white Yamaha Fazzio).
* **Helmis Pipeline**: Routes to Gemini 3.5 Flash $\rightarrow$ analyzes video frames $\rightarrow$ accurately identifies Yamaha Fazzio without synthetic prior hallucinations.

### 44. Handwritten Whiteboard Notes Extraction
* **User (Gilang sends photo of whiteboard)**: *"Catat action items dari foto ini"*
* **Helmis Action**: OCR extracts bullet points $\rightarrow$ creates structured tasks.

### 45. Restaurant Receipt Bill Splitting
* **User (Bunga sends photo of bill)**: *"Berapa total makanan Bunga vs Gilang?"*
* **Helmis Action**: Reads line items, calculates subtotal, tax, and service charges.

### 46. Business Card Contact Ingestion
* **User (Gilang sends photo of business card)**: *"Simpen kontak ini ya"*
* **Helmis Action**: Extracts Name, Phone, Company, Email $\rightarrow$ calls `add_person(...)`.

---

## Category G: Cross-Party Relays & Executive Secretarial Workflows

### 47. Cross-Party Relay with Delayed Reminder
* **User (Gilang DM)**: *"Tolong kasih tau Bunga kalau aku lagi di jalan dan bakal telat 15 menit, terus ingetin aku buat telpon dia pas sampe"*
* **Helmis Action**:
  1. `send_whatsapp_message(recipient="Bunga", text="Hai Bunga, Gilang menginfokan bahwa dia sedang di jalan dan kemungkinan terlambat sekitar 15 menit ya.")`
  2. `add_task("Telpon Bunga setelah sampai", "Hari ini 19:30 WIB", "Gilang")`
* **Helmis Reply to Gilang**: *"Siap Gilang, sudah saya kabari Bunga dan task untuk telpon Bunga sudah dicatat."*

### 48. Heavy Research with Thinking-Out-Loud Status Update
* **User (Gilang DM)**: *"Bandingkan 3 venue wedding outdoor di Bogor lengkap sama kapasitas dan estimasi harga"*
* **Helmis Action**:
  1. Calls `send_status_update("Sedang mengumpulkan perbandingan venue wedding outdoor di Bogor...")` $\rightarrow$ sends quick WhatsApp acknowledgment.
  2. Executes web research and synthesizes structured comparison table.
* **Helmis Final Reply**: Delivers complete comparison report.

### 49. Cross-Party Schedule Availability Check
* **User (Gilang DM)**: *"Bunga ada jadwal kosong ga besok sore buat nemenin ke dokter?"*
* **Helmis Action**: Checks Bunga's task calendar $\rightarrow$ identifies free window between 14:00 and 17:00.

### 50. Group Announcement Triggered from Private DM
* **User (Bunga DM)**: *"Mis, tolong umumin di grup Trio kalau besok kita mulai beres-beres rumah jam 9 pagi"*
* **Helmis Action**:
  1. Dispatches message to Trio Group.
  2. Creates shared task in calendar.
  3. Confirms completion to Bunga in DM.
