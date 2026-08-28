# Helmis Backlog & Issue Tracker

Dokumen ini mencatat seluruh backlog masalah, temuan root-cause dari runtime log produksi, serta rencana perbaikan arsitektural untuk agen Helmis.

---

## Ringkasan Backlog

| ID | Kategori | Masalah / Fitur | Prioritas | Status |
| :--- | :--- | :--- | :---: | :---: |
| **[BACKLOG-01]** | Web & Tools | Pembaca Google Docs, Spreadsheets, Slides, & Web URL Publik | `P0 - High` | ✅ Completed |
| **[BACKLOG-02]** | Architecture | Temp Sandbox Workspace untuk File Sementara & URL Cache | `P0 - High` | ✅ Completed |
| **[BACKLOG-03]** | Agent & Guardrails | Eliminasi Halusinasi Konfirmasi Aksi (Two-Step & Strict State Guardrail) | `P0 - High` | 📋 Planned |
| **[BACKLOG-04]** | Vault & Files | Penanganan Bookmark Link vs Dokumen Fisik Brankas | `P1 - Medium` | 📋 Planned |
| **[BACKLOG-05]** | Memory & Vault | Parser Dokumen Microsoft Office (`.pptx`, `.docx`, `.xlsx`) di `read_vault_file` | `P1 - Medium` | 📋 Planned |
| **[BACKLOG-06]** | WhatsApp Engine | Sinkronisasi `media_data` Biner pada Mid-Turn Steering | `P2 - Low` | 📋 Planned |
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
* **Masalah:**
  Pada turn WhatsApp, Gemini Flash Lite terkadang langsung membalas percakapan di Step 1 (misal: *"Sip, tugas ... sudah Helmis tandai selesai ya."*) tanpa pernah memanggil tool database (`complete_task` / `delete_task` / `add_task`). Akibatnya, status tugas di database tidak berubah sama sekali, namun user mengira tugas sudah selesai.
* **Root Cause:**
  Model diizinkan mengembalikan teks pada step 1. Guardrail `verify_action_fidelity()` hanya memvalidasi hasil jika ada tool mutasi yang dijalankan (`if not executed_tools: return cleaned_text`).
* **Solusi Rencana:**
  1. **Anti-Hallucination Regex Guardrail:** Di `guardrails.py`, jika teks balasan mengklaim mutasi data (*"sudah ditandai selesai"*, *"berhasil dihapus"*, *"sudah dicatat"*), tetapi `executed_tools` tidak mencatat eksekusi tool terkait, cegah teks tersebut dan paksa agen mengeksekusi tool terlebih dahulu.
  2. **Two-Step Tool Execution Prompting:** Perjelas aturan sistem di `system-prompt.md` bahwa konfirmasi tindakan mutasi **dilarang keras** diucapkan sebelum tool mengembalikan status sukses.

---

### [BACKLOG-04] Penanganan Bookmark Link vs Dokumen Fisik Brankas
* **Masalah:**
  Ketika user mengirim link (misal link presentasi), agen menyimpannya sebagai file dummy `Link_Presentasi.md` (158 bytes) tanpa isi konten URL di dalamnya. Saat user meminta filenya dikirim kembali (`send_vault_file`), Helmis mengirim file `.md` mentah sebagai lampiran dokumen WhatsApp, bukan teks link.
* **Solusi Rencana:**
  1. Bedakan penyimpanan **Notes / Bookmark** dengan **File Dokumen**.
  2. Jika user meminta link dikirim ulang, kirimkan sebagai pesan teks bubble WhatsApp beserta keterangannya, bukan file attachment markdown kosong.

---

### [BACKLOG-05] Parser Dokumen Microsoft Office (`.pptx`, `.docx`, `.xlsx`) di `read_vault_file`
* **Masalah:**
  `read_vault_file()` di `src/memory/vault.py` hanya mendukung ekstraksi teks dari `.pdf` dan plain text. File `.pptx`, `.docx`, dan `.xlsx` diperlakukan sebagai binary mentah (`[File Biner ...]`), sehingga agen tidak bisa membaca teks atau slide di dalamnya saat diambil dari brankas.
* **Solusi Rencana:**
  1. Integrasikan `python-pptx` untuk membaca teks per slide, judul, dan bullet points dari file `.pptx`.
  2. Integrasikan `python-docx` untuk membaca paragraf dan tabel dari file `.docx`.
  3. Integrasikan `openpyxl` untuk membaca sheet, header, dan baris dari file `.xlsx`.

---

### [BACKLOG-06] Sinkronisasi `media_data` Biner pada Mid-Turn Steering
* **Masalah:**
  Jika user mengirim teks lalu 2 detik kemudian mengirim file media saat turn sedang berlangsung, label teks disuntikkan ke prompt (`[Lampiran Media: file.pptx]`), tetapi payload biner `media_data` tidak diperbarui pada argumen `execute_tool_call`. Akibatnya, `save_vault_file` menganggap `media_data` bernilai `None` dan menyimpan file stub 122 bytes.
* **Solusi Rencana:**
  Perbarui objek `media_data` di dalam context loop saat mailbox mid-turn di-drain, sehingga eksekusi tool berikutnya mendapatkan byte biner file yang baru masuk.

---

### [BACKLOG-07] Standarisasi Format Task List, Timeline & Pemisahan Default Per Assignee
* **Status:** `✅ Completed (Deployed)`
* **Implementasi:**
  1. **Hierarchical WhatsApp Layout:** Penomoran urut (`1.`, `2.`), sub-line berjenjang (`└ Deadline: ...`), dan double line breaks antar-item untuk menghindari tampilan padat (*wall of text*).
  2. **Pemisahan Default Assignee:** Daftar tugas otomatis dikelompokkan menjadi `*Tugas Gilang:*`, `*Tugas Bunga:*`, `*Tugas Bersama:*`, dan `*Tindakan Otomatis Helmis:*`.
  3. **Konsistensi Header:** Pembatasan penanda blockquote (`>`) hanya untuk judul utama paling atas (`> *Daftar Tugas Aktif*`), sementara section header menggunakan Bold bersih tanpa `>` agar konsisten di WhatsApp.
