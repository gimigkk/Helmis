---
name: pdf-toolkit
description: Manipulate, merge, split, compress, convert (PDF ⇄ DOCX, Photos ➔ PDF), and render PDF pages to images.
---

# PDF Toolkit & Document Manipulation Skill

## Purpose
Perform high-performance, local PDF manipulations, conversions, page extractions, and document transformations without third-party web services or file size restrictions.

---

## Operations & Tool Invariants (`process_pdf`)

All PDF operations are executed through the single unified tool `process_pdf(action="...", target_files=[...], ...)`:

### 1. Merging PDFs (`action="merge"`)
- **Zero-Margin Native Format (Default)**: `page_sizing="original"`. Combines PDFs preserving each page's native aspect ratio and dimensions with **zero added outer white margins / zero letterboxing**.
- **Uniform Standard Format**: `page_sizing="a4"`. Normalizes disparate page sizes (Letter, receipts, slides) into a uniform A4 layout with proportional centering.
- Example: `process_pdf(action="merge", target_files=["bab1.pdf", "bab2.pdf"], page_sizing="original", output_filename="laporan_lengkap.pdf")`.

### 2. Splitting & Page Extraction (`action="split"`)
- Slice single pages or complex page ranges: `pages="1-3, 5, 8-10"`, `pages="last"`, `pages="odd"`, `pages="even"`.
- Optional rotation: `rotate_deg=90`, `180`, or `270`.
- Example: `process_pdf(action="split", target_files=["modul.pdf"], pages="3-7", output_filename="modul_bab2.pdf")`.

### 3. Rendering Page as WhatsApp Photo Preview (`action="render_image"`)
- Render a specific PDF page to a crisp PNG/JPG image (150–200 DPI).
- **Delivery**: Immediately follow with `send_vault_file(file_id_or_name="...", as_document=False)` so WhatsApp renders it as a **native inline photo preview bubble** directly in chat.
- Example: `process_pdf(action="render_image", target_files=["laporan.pdf"], page_number=4, format="png")`.

### 4. Photos / Images to Multi-Page PDF (`action="images_to_pdf"`)
- Compiles multiple camera photos, scans, or receipts (JPG, PNG, WEBP) into a single PDF.
- **Zero-Margin Fit (Default)**: `page_sizing="fit_image"`. Page dimensions match exact image dimensions with zero outer white pixels.
- **Uniform A4**: `page_sizing="a4"`. Centers images onto standard A4 pages.
- Example: `process_pdf(action="images_to_pdf", target_files=["nota_1.jpg", "nota_2.jpg"], page_sizing="fit_image", output_filename="bukti_pengeluaran.pdf")`.

### 5. PDF to Word DOCX (`action="to_docx"`)
- Converts PDF text flow, multi-columns, data tables, and formatting into an editable Microsoft Word `.docx`.
- Example: `process_pdf(action="to_docx", target_files=["surat_perjanjian.pdf"], output_filename="surat_perjanjian.docx")`.

### 6. Word DOCX to PDF (`action="from_docx"`)
- Converts a Word `.docx` file into a high-fidelity, printable PDF.
- Example: `process_pdf(action="from_docx", target_files=["draft_kontrak.docx"], output_filename="draft_kontrak.pdf")`.

### 7. PDF Compression (`action="compress"`)
- Deflates uncompressed streams, purges orphan objects, and downsamples high-res images to 150 DPI.
- Example: `process_pdf(action="compress", target_files=["portofolio.pdf"], output_filename="portofolio_ringan.pdf")`.

---

## Response & Dispatching Standards
- **Destination Invariant (`recipient="current"`)**: Always dispatch the generated file to the active conversation using `send_vault_file(file_id_or_name=..., recipient="current")`. If the user asked in the group chat, it MUST be sent directly to the group chat. Never redirect files to private DM unless the user explicitly requests private delivery (*"kirim ke japri"*, *"kirim ke DM gw"*).
- Adhere strictly to WhatsApp native typography (`*bold*`, `_italics_`) with **strict zero emojis**.
