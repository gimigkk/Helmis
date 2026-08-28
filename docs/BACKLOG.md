# Helmis Backlog & Issue Tracker

Dokumen ini mencatat seluruh backlog masalah, temuan root-cause dari runtime log produksi, serta rencana perbaikan arsitektural untuk agen Helmis.

---

## Ringkasan Backlog

| ID | Kategori | Masalah / Fitur | Prioritas | Status |
| :--- | :--- | :--- | :---: | :---: |
| **[BACKLOG-01]** | Web & Tools | Pembaca Google Docs, Spreadsheets, Slides, & Web URL Publik | `P0 - High` | ✅ Completed |
| **[BACKLOG-02]** | Architecture | Temp Sandbox Workspace untuk File Sementara & URL Cache | `P0 - High` | ✅ Completed |
| **[BACKLOG-03]** | Agent & Guardrails | Eliminasi Halusinasi Konfirmasi Aksi (Two-Step & Strict State Guardrail) | `P0 - High` | ✅ Completed |
| **[BACKLOG-04]** | Vault & Files | Penanganan Bookmark Link vs Dokumen Fisik Brankas | `P1 - Medium` | 📋 Planned |
| **[BACKLOG-05]** | Memory & Vault | Parser Dokumen Microsoft Office (`.pptx`, `.docx`, `.xlsx`) di `read_vault_file` | `P1 - Medium` | ✅ Completed |
| **[BACKLOG-06]** | WhatsApp Engine | Sinkronisasi `media_data` Biner pada Mid-Turn Steering | `P2 - Low` | ✅ Completed |
| **[BACKLOG-07]** | Typography & UX | Standarisasi Format Task List, Timeline & Pemisahan Default Per Assignee | `P1 - Medium` | ✅ Completed |

---

## Detail Backlog & Rencana Solusi

### [BACKLOG-01] Pembaca Google Docs, Spreadsheets, Slides, & Web URL Publik
* **Status:** `✅ Completed (Deployed)`
* **Implementasi:**
  1. **Tool `read_url` & Aliases:** Terdaftar di `src/tools/web.py` dan `src/tools/schema.py` dengan alias khusus (`read_google_sheet`, `read_google_doc`, `read_google_slides`, `read_web_page`).
  2. **Multi-Format Google Workspace Engine (`src/tools/google_reader.py`):**
     - **Google Sheets:** Standard CSV direct export dan **Published Sheets (`pubhtml`) Multi-Tab Table Parser** tanpa dependensi eksternal (`GoogleSheetsHTMLTableParser`).
     - **Google Docs:** Direct UTF-8 clean text export dengan proteksi batasan panjang.
     - **Google Slides:** Direct PDF export & ekstraksi teks per slide via `pypdf`.
     - **Google Drive Files & Web:** Direct download & scraper bersih dengan proteksi SSRF (blokir IP privat/localhost).
  3. **Kesadaran Snapshot Non-Realtime:** Metadata `snapshot_at` WIB, flag `force_refresh=True` saat dokumen baru diedit, dan deteksi proteksi dokumen privat (`accounts.google.com/ServiceLogin`).
  4. **Footnote Transparan:** Guardrail otomatis mendeteksi dan merender footnote spesifik di WhatsApp (`↳ read_google_sheet`, `↳ read_google_doc`, dll).

---

### [BACKLOG-02] Temp Sandbox Workspace untuk File Sementara & URL Cache
* **Status:** `✅ Completed (Deployed)`
* **Implementasi:**
  1. Dibuat modul `src/memory/sandbox.py` dengan lokasi kerja terisolasi di `data/sandbox/` (atau `/app/data/sandbox/` di kontainer).
  2. Snapshot unduhan dan hasil konversi sementara di-cache dengan TTL (30 menit) dan otomatis dibersihkan (file > 1 jam atau kapasitas > 250MB via LRU).
  3. Menjamin zero vault pollution pada `file_catalog.json` saat membaca dokumen online.
  4. Proteksi keamanan path traversal dengan `is_safe_sandbox_path()`.

---

### [BACKLOG-03] Eliminasi Halusinasi Konfirmasi Aksi (Two-Step & Strict State Guardrail)
* **Status:** `✅ Completed (Deployed)`
* **Implementasi:**
  1. **State Mutation Claim Detector (`detect_unexecuted_mutation_claims` di `src/agent/guardrails.py`):**
     - Mendeteksi klaim penyelesaian tugas (`complete_task`), penghapusan data (`delete_task`, `delete_note`, `delete_memory`), pencatatan tugas baru (`add_task`), penyimpanan ke brankas (`save_vault_file`), dan pengiriman pesan/file (`send_whatsapp_message`, `send_vault_file`).
  2. **Dynamic Turn Interception (`src/agent/loop.py`):**
     - Jika model mencoba mengembalikan teks konfirmasi pada Step 1 tanpa memanggil tool terkait, teks tersebut **langsung dicegat dan ditolak**.
     - Sistem menyuntikkan instruksi tegas: *"SYSTEM INTEGRITY FAULT: Kamu mengklaim telah melakukan tindakan, tetapi BELUM memanggil functionCall ke tool terkait! Eksekusi functionCall sekarang."*
  3. **Fallback Fidelity:**
     - Jika batas langkah tercapai tanpa eksekusi tool, teks klaim palsu otomatis diganti dengan pernyataan jujur bahwa aksi belum diproses di database.

---

### [BACKLOG-04] Penanganan Bookmark Link vs Dokumen Fisik Brankas
* **Masalah:**
  Ketika user mengirim link (misal link presentasi), agen menyimpannya sebagai file dummy `Link_Presentasi.md` (158 bytes) tanpa isi konten URL di dalamnya. Saat user meminta filenya dikirim kembali (`send_vault_file`), Helmis mengirim file `.md` mentah sebagai lampiran dokumen WhatsApp, bukan teks link.
* **Solusi Rencana:**
  1. Bedakan penyimpanan **Notes / Bookmark** dengan **File Dokumen**.
  2. Jika user meminta link dikirim ulang, kirimkan sebagai pesan teks bubble WhatsApp beserta keterangannya, bukan file attachment markdown kosong.

---

### [BACKLOG-05] Parser Dokumen Microsoft Office (`.pptx`, `.docx`, `.xlsx`) di `read_vault_file`
* **Status:** `✅ Completed (Deployed)`
* **Implementasi:**
  1. **PowerPoint Presentation Parser (`python-pptx`):** Mengekstrak teks per slide terstruktur (`--- Slide 1 dari N ---`), judul slide, bullet point berindentasi, tabel di dalam slide, dan catatan presenter (*speaker notes*), memudahkan instruksi spesifik seperti *"baca slide terakhir"*.
  2. **Word Document Parser (`python-docx`):** Mengekstrak heading terstruktur (`### Heading`), paragraf teks, serta tabel Word ke format Markdown table.
  3. **Excel Spreadsheet Parser (`openpyxl`):** Mengekstrak seluruh sheet, header kolom, dan baris data ke format Markdown table bersih dengan proteksi pemotongan (max 100 baris per sheet) untuk mencegah *token overflow*.

---

### [BACKLOG-06] Sinkronisasi `media_data` Biner pada Mid-Turn Steering
* **Status:** `✅ Completed (Deployed)`
* **Implementasi:**
  1. **Sinkronisasi Biner:** Saat user mengirim lampiran media mid-turn (misal file dikirim 2 detik setelah teks awal), `drain_and_inject_mid_turn_mailbox()` mengunduh payload biner dan menyimpannya ke `turn_state["media_data"]`.
  2. **Multimodal Inline Data untuk Gemini:** Jika media berupa gambar atau PDF, selain banner teks, sistem juga menyuntikkan part `inlineData: {"mimeType": ..., "data": ...}` sehingga model Gemini langsung dapat memproses visual dokumen/gambar tersebut.
  3. **Eksekusi Tool dengan Payload Terbaru:** `execute_tool_call()` di `src/agent/loop.py` otomatis menggunakan payload `media_data` terbaru, memastikan tool seperti `save_vault_file` menyimpan file biner utuh (misal file 500KB) dan bukan lagi stub 122 bytes.

---

### [BACKLOG-07] Standarisasi Format Task List, Timeline & Pemisahan Default Per Assignee
* **Status:** `✅ Completed (Deployed)`
* **Implementasi:**
  1. **Hierarchical WhatsApp Layout:** Penomoran urut (`1.`, `2.`), sub-line berjenjang (`└ Deadline: ...`), dan double line breaks antar-item untuk menghindari tampilan padat (*wall of text*).
  2. **Pemisahan Default Assignee:** Daftar tugas otomatis dikelompokkan menjadi `*Tugas Gilang:*`, `*Tugas Bunga:*`, `*Tugas Bersama:*`, dan `*Tindakan Otomatis Helmis:*`.
  3. **Konsistensi Header:** Pembatasan penanda blockquote (`>`) hanya untuk judul utama paling atas (`> *Daftar Tugas Aktif*`), sementara section header menggunakan Bold bersih tanpa `>` agar konsisten di WhatsApp.
