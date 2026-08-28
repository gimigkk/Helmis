# Helmis Backlog & Issue Tracker

Dokumen ini mencatat seluruh backlog masalah, temuan root-cause dari runtime log produksi, serta rencana perbaikan arsitektural untuk agen Helmis.

---

## Ringkasan Backlog

| ID | Kategori | Masalah / Fitur | Prioritas | Status |
| :--- | :--- | :--- | :---: | :---: |
| **[BACKLOG-01]** | Web & Tools | Pembaca Google Docs, Spreadsheets, Slides, & Web URL Publik | `P0 - High` | 📋 Planned |
| **[BACKLOG-02]** | Architecture | Temp Sandbox Workspace untuk File Sementara & URL Cache | `P0 - High` | 📋 Planned |
| **[BACKLOG-03]** | Agent & Guardrails | Eliminasi Halusinasi Konfirmasi Aksi (Two-Step & Strict State Guardrail) | `P0 - High` | 📋 Planned |
| **[BACKLOG-04]** | Vault & Files | Penanganan Bookmark Link vs Dokumen Fisik Brankas | `P1 - Medium` | 📋 Planned |
| **[BACKLOG-05]** | Memory & Vault | Parser Dokumen Microsoft Office (`.pptx`, `.docx`, `.xlsx`) di `read_vault_file` | `P1 - Medium` | 📋 Planned |
| **[BACKLOG-06]** | WhatsApp Engine | Sinkronisasi `media_data` Biner pada Mid-Turn Steering | `P2 - Low` | 📋 Planned |

---

## Detail Backlog & Rencana Solusi

### [BACKLOG-01] Pembaca Google Docs, Spreadsheets, Slides, & Web URL Publik
* **Masalah:**
  Ketika user mengirimkan link Google Docs/Spreadsheet/Presentation atau link web publik dan menanyakan isinya (misal: *"kelompok berapa di sheet ini?"*), agen tidak memiliki tool untuk membaca isi halaman/dokumen. Agen mencoba melakukan `web_search("site:docs.google.com/...")` yang selalu mengembalikan 0 hasil, lalu berhalusinasi dari memori lama atau gagal menjawab.
* **Root Cause:**
  Tool `web.py` hanya memiliki `web_search` (DuckDuckGo/Tavily), belum ada tool pembaca URL (`read_url` / `read_web_page`).
* **Solusi Rencana:**
  1. Buat tool `read_url` di `src/tools/web.py` dengan deteksi URL Google Workspace:
     - **Google Sheets:** Fetch via `https://docs.google.com/spreadsheets/d/{id}/export?format=csv` (parse menjadi tabel markdown terstruktur).
     - **Google Docs:** Fetch via `https://docs.google.com/document/d/{id}/export?format=txt` (parse plain text UTF-8).
     - **Google Slides:** Fetch via `https://docs.google.com/presentation/d/{id}/export/pdf` (ekstrak per slide via `pypdf`).
     - **Halaman Web Biasa:** Fetch HTML dan ekstrak konten utama yang bersih (strip scripts/styles).
  2. **Kesadaran Snapshot Non-Realtime (*Epistemic Humility*):**
     - Agen harus sadar penuh bahwa ia **tidak terhubung secara live-stream/kolaboratif real-time** ke Google Docs (tidak bisa melihat kursor live atau ketikan yang sedang berlangsung saat itu juga).
     - Yang diakses adalah **snapshot titik-waktu statis (*downloaded export snapshot*)** pada detik tool dijalankan.
     - Tool menyertakan metadata waktu snapshot (`snapshot_at`), dan agen selalu melakukan fetch ulang jika user memberitahu ada editan baru (*"udah gue ubah barusan"*).
  3. Deteksi hak akses dokumen: Jika redirect ke `accounts.google.com/ServiceLogin` (dokumen privat), beri pesan informatif kepada user untuk mengubah akses sharing menjadi *"Anyone with the link can view"*.

---

### [BACKLOG-02] Temp Sandbox Workspace untuk File Sementara & URL Cache
* **Masalah:**
  Saat ini semua file yang diunduh atau disimpan langsung masuk ke brankas permanen (`/app/data/vault/` dan `file_catalog.json`). Dokumen Google Docs/Sheets bersifat dinamis (dapat diedit sewaktu-waktu oleh user), dan user sering kali hanya ingin bertanya sekilas tanpa ingin dokumen tersebut mengotori database brankas permanen.
* **Solusi Rencana:**
  1. Buat direktori kerja sementara (sandbox workspace) di `/app/data/sandbox/` (atau `/tmp/helmis_sandbox/`).
  2. Semua hasil fetch link, unduhan snapshot Google Docs/Sheets, konversi sementara, atau pembacaan web disimpan di sandbox sebagai file cache sementara dengan masa berlaku (TTL) singkat (15–30 menit).
  3. Brankas permanen (`save_vault_file`) hanya digunakan ketika ada instruksi eksplisit dari user (*"simpan ke brankas"*, *"catat file ini"*).
  4. Tambahkan mekanisme auto-cleanup (membersihkan file sandbox yang lebih lama dari 1 jam).

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
