# Laporan Hasil Kerja Pengembangan DOAJ_Reviewer

Periode laporan: sampai **16 Februari 2026**

## 1. Ringkasan Eksekutif

- Aplikasi `DOAJ_Reviewer` berhasil dibangun sebagai **review assistant** untuk memeriksa submission jurnal terhadap panduan DOAJ.
- Sistem sudah mendukung alur realistis: user mengisi form URL, aplikasi crawl halaman, ekstrak teks natural language, evaluasi rule, lalu keluarkan keputusan `pass`, `fail`, atau `need_human_review`.
- Arsitektur saat ini adalah **deterministic rule-based engine** (heuristic NLP + regex), belum memakai API OpenAI/LLM eksternal.
- Fitur operasional utama sudah tersedia: simulasi web, batch spreadsheet, artifact JSON/Markdown/TXT, export CSV, fallback manual saat WAF, dan dokumentasi kolaborasi via GitHub/Codespaces.
- Status repo lokal dan remote sudah sinkron penuh.

## 2. Latar Belakang dan Tujuan Awal

- Kebutuhan utama: aplikasi bukan untuk membantu mengisi form DOAJ, tetapi untuk **mereview jawaban pendaftar**.
- Setiap field berbasis URL harus dikunjungi, teks dibaca, dan dicocokkan terhadap rule DOAJ.
- Fokus evaluasi mencakup field must dan non-must, dengan output keputusan plus alasan.
- Kebutuhan tambahan penting: evaluasi endogeny, dukungan website JS-heavy, handling kondisi WAF, dan opsi human review saat bukti kurang.

## 3. Tahapan Pekerjaan yang Telah Diselesaikan

1. Klarifikasi requirement dan rule bisnis.
2. Menentukan keputusan evaluasi: `pass`, `fail`, `need_human_review`.
3. Menyusun rule coverage berdasarkan referensi DOAJ:
   - `https://doaj.org/apply/`
   - `https://doaj.org/apply/guide/`
   - `https://doaj.org/apply/transparency/`
   - `https://doaj.org/apply/copyright-and-licensing/`
4. Menambahkan ketentuan endogeny sesuai diskusi:
   - Issue-based: dua edisi terbaru.
   - Continuous: 1 tahun kalender, minimum 5 artikel.
5. Membuat repository terpisah `DOAJ_Reviewer` (bukan sub-repo di `doa_journals`).
6. Implementasi engine inti, schema, test, simulasi UI, dan CI.
7. Perbaikan bertahap berdasarkan hasil simulasi user, termasuk kasus “No policy text was extracted”.
8. Penyesuaian UI ke Bahasa Inggris dan urutan field mengikuti alur form DOAJ.
9. Penyempurnaan evaluator editorial board/reviewer:
   - Perhitungan komposisi dipisah.
   - Editorial board diberi keringanan komposisi.
   - Reviewer tetap wajib komposisi sesuai rule.
10. Penanganan WAF/Cloudflare, fallback manual text/PDF, dan retry/throttle.
11. Penambahan fitur output hasil: print ke PDF dan download text.
12. Penyusunan dokumentasi GitHub/Codespaces, changelog, dan template release notes.

## 4. Implementasi Teknis Utama

- Modul crawling dan parsing: `src/doaj_reviewer/web.py`
- Intake raw submission ke structured submission: `src/doaj_reviewer/intake.py`
- Evaluator rules (must + supplementary): `src/doaj_reviewer/basic_rules.py`
- Runner agregasi review: `src/doaj_reviewer/review.py`
- Simulasi web app lokal/Codespaces: `src/doaj_reviewer/sim_server.py`
- Batch processing spreadsheet: `src/doaj_reviewer/spreadsheet_batch.py`
- Endogeny evaluator dan reporting:
  - `src/doaj_reviewer/endogeny.py`
  - `src/doaj_reviewer/reporting.py`

## 5. Fitur yang Sudah Aktif

- Review must rules DOAJ dan supplementary rules non-must.
- Endogeny audit dengan evidence dan matched articles.
- Hybrid fetch mode:
  - Static fetch.
  - Auto fallback ke Playwright untuk halaman JS-heavy.
- Dukungan simulasi form web realistis.
- Export artifact per run:
  - `submission.raw.json`
  - `submission.structured.json`
  - `review-summary.json`
  - `review-summary.md`
  - `review-summary.txt`
  - `endogeny-result.json`
  - `endogeny-report.md`
- Export CSV agregasi semua run.
- Tombol `Reset form`.
- Tombol `Print to PDF` (melalui dialog print browser).
- Tombol `Download text` (plain `.txt`).

## 6. Penyesuaian Rule Sesuai Diskusi

- Urutan field dan pemeriksaan diselaraskan dengan alur DOAJ form.
- Prioritas ISSN elektronik.
- Peer review type detection + cek pernyataan minimal dua reviewer.
- License disesuaikan opsi lisensi yang diminta.
- Copyright ownership dianalisis author vs publisher.
- Aims & Scope: jika hanya scope tanpa aims/focus diberi catatan.
- Editorial board:
  - Minimum anggota.
  - Komposisi institusi untuk board bersifat informasional.
- Reviewer:
  - Minimum reviewer.
  - Komposisi institusi reviewer wajib sesuai threshold.
- Endogeny:
  - Issue-based dua edisi terakhir.
  - Continuous satu tahun kalender.
- Jika data/afiliasi tidak memadai: `need_human_review` dengan catatan.

## 7. Penanganan WAF dan Kasus Sulit Crawl

- Deteksi challenge page (Cloudflare/Akamai/Imperva/Sucuri/generic WAF).
- Jika policy URL terblokir:
  - Auto diarahkan ke `need_human_review`.
  - Catatan eksplisit WAF dimasukkan ke notes/evidence.
- Per-domain throttling + exponential retry untuk mengurangi blok/rate-limit.
- Manual fallback di UI:
  - Paste text policy.
  - Upload PDF policy per field (best effort extract via `pypdf`/`PyPDF2` jika tersedia).

## 8. Dokumentasi dan Operasional

- README utama diperbarui dengan update terbaru.
- `CHANGELOG.md` dibuat untuk riwayat perubahan.
- `RELEASE_NOTES_TEMPLATE.md` dibuat untuk rilis/tag berikutnya.
- `CONTRIBUTING.md` dan `SUPPORT.md` disiapkan.
- Panduan beginner English untuk kolaborator non-teknis via Codespaces:
  - `CODESPACES_GUIDE_EN.md`

## 9. Quality Assurance

- Test suite unit/regression aktif dan berjalan baik.
- Hasil pengujian terbaru: **37 test, seluruhnya lulus**.
- CI workflow sudah tersedia untuk validasi otomatis.

## 10. Ringkasan Commit Utama

- `a3f7ada` Initial implementation.
- `4793275` Repository About/support documentation.
- `ef23a03` English Codespaces beginner guide.
- `c5cd359` WAF handling, manual fallback, result export improvements.
- `080c60e` README updates + changelog.
- `8d4ccf5` Release notes template.

## 11. Status Repositori Saat Ini

- Local dan remote sudah sinkron.
- Branch `main` == `origin/main`.
- Tidak ada selisih commit.

## 12. Catatan Rencana Lanjutan (Ditunda)

- UAT 3 skenario utama (normal, JS-heavy, WAF + manual fallback).
- Pembuatan release resmi (`v0.1.0`) dengan release notes.
- Checklist reviewer 1 halaman untuk standar uji kolega.
- Penyusunan backlog issue prioritas berikutnya.

## 13. Metodologi Pengembangan Coding yang Dipakai

Metodologi yang dipakai selama pengembangan proyek ini adalah kombinasi:

- `Iterative Incremental Development`
- `Schema-First Design`
- `Deterministic Rule-Based NLP Pipeline`
- `Test-Driven Hardening`

### 13.1 Requirement-Driven Iteration

Alur kerja dilakukan secara bertahap:

1. Klarifikasi kebutuhan bisnis/rule.
2. Implementasi fitur minimal yang memenuhi kebutuhan.
3. Uji dengan simulasi nyata.
4. Revisi perilaku sistem berdasarkan temuan.
5. Ulangi siklus sampai stabil.

Pendekatan ini disebut `iterative-incremental` karena penambahan fitur dilakukan per bagian kecil yang dapat diuji segera, bukan sekaligus dalam satu batch besar.

### 13.2 Schema-First (Contract-First) Development

Sebelum logika evaluator berjalan, kontrak data didefinisikan melalui JSON Schema:

- `submission-raw.schema.json` untuk input awal.
- `submission.schema.json` untuk hasil intake terstruktur.

Manfaatnya:

- Validasi input lebih ketat.
- Integrasi antar modul lebih stabil.
- Perubahan perilaku sistem lebih mudah ditelusuri karena ada kontrak data formal.

### 13.3 Arsitektur Pipeline Deterministik

Arsitektur sistem disusun sebagai pipeline yang jelas:

`Raw Input -> Crawl -> Parse -> Normalize -> Evaluate Rules -> Aggregate Decision -> Report/Artifacts`

Sifat deterministik berarti: input sama akan menghasilkan output yang konsisten (tanpa randomness model generatif).

### 13.4 Rule-Based NLP dan Heuristic Extraction

Analisis teks kebijakan dilakukan dengan:

- `regex pattern matching`
- `signal detection`
- `heuristic scoring`

Pendekatan ini sesuai kategori:

- `Rule-Based Expert System`
- `Deterministic Heuristic NLP Engine`

Artinya sistem membaca natural language dengan aturan eksplisit yang bisa diaudit, bukan inferensi probabilistik dari LLM.

### 13.5 Hybrid Retrieval Strategy

Untuk pengambilan konten web digunakan strategi hybrid:

1. Ambil HTML statik terlebih dahulu.
2. Jika halaman terdeteksi JS-heavy, lakukan fallback render browser (Playwright).

Metode ini meningkatkan keberhasilan ekstraksi untuk website berbasis framework/tema modern.

### 13.6 Fail-Safe Decisioning dan Human-in-the-Loop

Logika keputusan didesain konservatif:

- `pass` bila bukti kuat dan memenuhi rule.
- `fail` bila bukti kuat dan melanggar rule.
- `need_human_review` bila bukti ambigu/kurang/terblokir.

Ini adalah pola `fail-safe` dan `human-in-the-loop` agar sistem tidak memaksakan keputusan otomatis saat confidence rendah.

### 13.7 Evidence-Centered Auditability

Setiap keputusan rule disertai:

- `notes` penjelasan.
- `evidence_urls`.
- `evidence` ringkasan crawl.
- `policy_pages` teks sumber.

Metode ini disebut `auditability-first`: reviewer manusia dapat menelusuri alasan keputusan secara transparan.

### 13.8 Metode Perhitungan Endogeny

Perhitungan endogeny diimplementasikan sebagai `policy-compliance metric`:

1. Ekstrak daftar editor/reviewer.
2. Ekstrak author/co-author dari artikel.
3. Normalisasi nama dan lakukan name matching.
4. Hitung rasio endogeny per unit ukur.
5. Bandingkan terhadap threshold DOAJ.

Mode evaluasi:

- `issue_based`: dua issue terbaru.
- `continuous`: satu tahun kalender terakhir (minimum 5 artikel).

### 13.9 WAF Resilience Method

Untuk website dengan proteksi (misalnya Cloudflare), dipakai pola ketahanan:

- `challenge detection` (halaman anti-bot/WAF).
- `throttling per domain`.
- `exponential backoff retry`.
- `manual fallback` (paste text/PDF) jika tetap terblokir.
- hasil diarahkan ke `need_human_review` dengan catatan eksplisit.

### 13.10 Quality Methodology

Kualitas dijaga melalui:

- `unit tests` untuk fungsi inti.
- `regression tests` untuk mencegah perilaku lama rusak.
- `mock-based tests` untuk skenario jaringan/crawl.
- `CI workflow` di GitHub Actions.

Pendekatan ini memastikan setiap perubahan rule tetap dapat diverifikasi secara konsisten.

## 14. Glossary Terminologi Teknis

- `Iterative Incremental Development`: pengembangan bertahap dengan siklus perbaikan berulang.
- `Schema-First / Contract-First`: kontrak data ditetapkan dulu, implementasi mengikuti kontrak tersebut.
- `Deterministic`: hasil konsisten untuk input yang sama.
- `Rule-Based Engine`: mesin keputusan berbasis aturan eksplisit.
- `Heuristic NLP`: analisis teks natural language berbasis pola praktis.
- `Regex`: ekspresi pola untuk pencocokan string/teks.
- `Human-in-the-Loop`: keputusan akhir melibatkan reviewer manusia saat diperlukan.
- `Fail-Safe`: saat ragu, sistem memilih jalur aman (`need_human_review`) bukan memaksakan keputusan.
- `Auditability`: kemampuan menelusuri alasan keputusan dari bukti.
- `Hybrid Fetch`: gabungan static fetch dan browser rendering.
- `WAF`: Web Application Firewall (contoh: Cloudflare).
- `Throttling`: pembatasan laju request untuk mengurangi block/rate limit.
- `Exponential Backoff`: retry berulang dengan jeda yang meningkat bertahap.
- `Artifact`: file keluaran hasil review (`json`, `md`, `txt`) per run.
- `Regression Test`: pengujian untuk memastikan perubahan baru tidak merusak fungsi lama.

## 15. Versi Siap Gambar Flowchart (Node-Level)

Bagian ini ditulis dalam format node agar mudah diterjemahkan menjadi flowchart visual.

### 15.1 Main Flow End-to-End 1 Submission

1. `[Start]` User membuka halaman simulasi.
2. `[Input/Output]` User mengisi form submission (URL wajib, URL opsional, publication model, js mode, manual fallback text/PDF jika diperlukan).
3. `[Process]` Sistem membentuk objek `raw submission`.
4. `[Process]` Sistem memvalidasi field wajib.
5. `[Decision]` Apakah validasi lolos?
6. `[Input/Output]` Jika tidak lolos, sistem kirim error validasi ke UI.
7. `[End]` Proses berhenti jika invalid.
8. `[Process]` Jika lolos, sistem membuat `run_id` dan folder artifact.
9. `[Process]` Sistem menyimpan `submission.raw.json`.
10. `[Process]` Sistem menjalankan intake untuk membentuk `submission.structured.json`.
11. `[Process]` Sistem menjalankan evaluasi rule must dan supplementary.
12. `[Process]` Sistem menghitung `overall_result`.
13. `[Process]` Sistem menyimpan artifact review dan endogeny (`json`, `md`, `txt`).
14. `[Input/Output]` Sistem mengirim hasil ke UI.
15. `[Input/Output]` UI menampilkan status, tabel hasil, warning, dan tautan artifact.
16. `[Decision]` Apakah user memilih ekspor?
17. `[Process]` Jika user pilih `Print to PDF`, browser membuka print dialog dan user memilih lokasi simpan lokal.
18. `[Process]` Jika user pilih `Download text`, browser mengunduh file `.txt`.
19. `[End]` Proses submission selesai.

### 15.2 Subflow Intake (Crawl, Parse, Normalize)

1. `[Start]` Intake menerima `raw submission`.
2. `[Process]` Sistem membaca semua URL berdasarkan kelompok rule.
3. `[Process]` Untuk setiap URL, sistem menerapkan throttling per domain.
4. `[Process]` Sistem melakukan fetch dengan retry dan exponential backoff.
5. `[Decision]` Apakah fetch berhasil?
6. `[Process]` Jika gagal, catat `crawl_note` sebagai evidence, lanjut URL berikutnya.
7. `[Process]` Jika berhasil, sistem parse HTML dan ekstrak teks.
8. `[Decision]` Apakah halaman terdeteksi sebagai challenge/WAF?
9. `[Process]` Jika ya, catat evidence WAF, jangan gunakan teks halaman itu sebagai policy text.
10. `[Process]` Jika tidak, simpan teks ke `policy_pages`.
11. `[Process]` Sistem ekstrak `role_people` dari halaman editorial/reviewer.
12. `[Process]` Sistem deduplikasi nama-role.
13. `[Decision]` Apakah publication model = `issue_based`?
14. `[Process]` Jika `issue_based`, crawl dua issue terbaru untuk ekstraksi artikel riset.
15. `[Process]` Jika `continuous`, crawl kandidat konten (latest + archive) untuk jendela satu tahun kalender.
16. `[Process]` Sistem melampirkan manual fallback text/PDF jika user menyediakannya.
17. `[Output]` Sistem menghasilkan `submission.structured.json`.
18. `[End]` Intake selesai.

### 15.3 Subflow Rule Evaluation

1. `[Start]` Runner membaca daftar check dari ruleset must.
2. `[Process]` Ambil satu rule must.
3. `[Decision]` Apakah evaluator rule tersedia?
4. `[Process]` Jika tidak tersedia, hasil rule `need_human_review`.
5. `[Process]` Jika tersedia, evaluator membaca `policy_pages` sesuai `rule_hint`.
6. `[Decision]` Apakah policy text tersedia?
7. `[Process]` Jika tidak tersedia, hasil rule `need_human_review` (dengan catatan WAF jika ada).
8. `[Process]` Jika tersedia, evaluator menjalankan deteksi sinyal (`regex` + heuristik).
9. `[Process]` Evaluator menetapkan `pass` atau `fail` atau `need_human_review`.
10. `[Process]` Evaluator mengisi `confidence`, `notes`, dan `evidence_urls`.
11. `[Decision]` Apakah masih ada must rule berikutnya?
12. `[Process]` Jika ada, kembali ke langkah evaluasi rule berikutnya.
13. `[Process]` Setelah must selesai, jalankan supplementary checks.
14. `[Output]` Hasil evaluasi lengkap siap untuk agregasi keputusan.
15. `[End]` Evaluasi rule selesai.

### 15.4 Subflow Endogeny

1. `[Start]` Evaluator endogeny menerima `structured submission`.
2. `[Process]` Sistem membaca `role_people` dan daftar artikel riset.
3. `[Process]` Sistem normalisasi nama editor/reviewer/author.
4. `[Process]` Sistem melakukan name matching untuk mendeteksi artikel terafiliasi endogeny.
5. `[Process]` Sistem menghitung metrik per unit: total artikel, matched artikel, rasio.
6. `[Decision]` Apakah publication model = `issue_based`?
7. `[Process]` Jika `issue_based`, evaluasi rasio pada dua issue terbaru.
8. `[Process]` Jika `continuous`, evaluasi rasio pada satu tahun kalender.
9. `[Decision]` Apakah data minimum terpenuhi (misal continuous minimal 5 artikel)?
10. `[Process]` Jika tidak terpenuhi, hasil `need_human_review`.
11. `[Decision]` Apakah rasio endogeny melebihi 25%?
12. `[Process]` Jika melebihi threshold, hasil `fail`.
13. `[Process]` Jika tidak melebihi threshold dan data cukup, hasil `pass`.
14. `[Output]` Sistem menyimpan `endogeny-result.json` dan `endogeny-report.md`.
15. `[End]` Evaluasi endogeny selesai.

### 15.5 Subflow Aggregate Decision dan Reporting

1. `[Start]` Sistem menerima hasil semua must checks.
2. `[Decision]` Apakah ada rule dengan hasil `fail`?
3. `[Process]` Jika ada, set `overall_result = fail`.
4. `[Decision]` Jika tidak ada fail, apakah ada `need_human_review`?
5. `[Process]` Jika ada, set `overall_result = need_human_review`.
6. `[Process]` Jika semua must pass, set `overall_result = pass`.
7. `[Process]` Sistem membentuk summary final.
8. `[Output]` Sistem menyimpan `review-summary.json`.
9. `[Output]` Sistem menyimpan `review-summary.md`.
10. `[Output]` Sistem menyimpan `review-summary.txt`.
11. `[Output]` Sistem kirim response hasil ke UI.
12. `[End]` Proses reporting selesai.

### 15.6 Catatan Konversi ke Diagram Visual

1. Gunakan simbol `Terminator` untuk `[Start]` dan `[End]`.
2. Gunakan simbol `Process` untuk langkah `[Process]`.
3. Gunakan simbol `Decision` untuk langkah `[Decision]`.
4. Gunakan simbol `Data/Input-Output` untuk langkah `[Input/Output]` dan `[Output]`.
5. Beri label panah keputusan dengan `Yes/No`.
6. Pisahkan minimal lima lane diagram: `UI`, `Validation`, `Intake`, `Rule Engine`, `Reporting`.

## 16. Framework dan Stack yang Digunakan

### 16.1 Ringkasan

- Implementasi saat ini **tidak menggunakan framework web besar** seperti Flask, FastAPI, atau Django.
- Aplikasi dibangun sebagai **custom Python application** berbasis `standard library`, dengan arsitektur `deterministic rule-based engine`.

### 16.2 Komponen Utama yang Dipakai

- Runtime bahasa: `Python >= 3.10`
- HTTP simulation server: `http.server.ThreadingHTTPServer` (standard library)
- HTTP fetch/crawling dasar: `urllib` (standard library)
- CLI interface: `argparse` (standard library)
- Data serialization: `json`, `csv` (standard library)
- Packaging/build: `setuptools` + `wheel` (melalui `pyproject.toml`)
- Testing: `unittest` (standard library)

### 16.3 Komponen Opsional (Conditional)

- `Playwright`: dipakai bila mode JS render aktif (`js_mode=auto|on`) untuk website JS-heavy.
- `pypdf` / `PyPDF2`: dipakai secara best effort untuk ekstraksi teks dari PDF manual fallback.

### 16.4 Istilah Teknis Metode Implementasi

- `Standard-library based backend`
- `Custom lightweight HTTP server`
- `Deterministic rule-based NLP pipeline`
- `Heuristic extraction engine`

Kesimpulan praktis:

- Ini adalah aplikasi backend Python ringan tanpa ketergantungan framework besar, dengan fokus pada kontrol rule yang eksplisit, auditability, dan kemudahan deployment di lingkungan sederhana (lokal/Codespaces/CI).

## 17. Panduan Operasional Codespaces (Updated)

Bagian ini ditambahkan agar laporan proyek dapat dipakai langsung sebagai panduan operasional, tanpa harus membuka dokumen terpisah.

### 17.1 Perubahan Utama Dibanding Panduan Sebelumnya

- Form simulasi sudah mengikuti urutan field terbaru.
- Tersedia aksi hasil: `Reset form`, `Print to PDF`, dan `Download text`.
- Untuk status `fail` dan `need_human_review`, tersedia `Review URLs` agar reviewer manusia dapat follow-up langsung.
- Troubleshooting diperluas untuk kasus nyata yang terjadi selama uji coba:
  - `HTTP ERROR 502`
  - path direktori Codespace tidak sesuai
  - tombol `Run simulation` / `Reset form` tidak merespons (cache browser)

### 17.2 Prasyarat

- Akun GitHub aktif.
- Browser modern.
- Koneksi internet stabil.

### 17.3 Membuat Codespace

1. Buka repo: `https://github.com/ikhwan-arief/DOAJ_Reviewer`
2. Klik `Code`.
3. Pilih tab `Codespaces`.
4. Klik `Create codespace on main`.
5. Tunggu VS Code browser terbuka penuh.

Catatan:

- Setiap penguji sebaiknya membuat Codespace sendiri.
- Jangan mengandalkan satu Codespace bersama untuk semua orang.

### 17.4 Verifikasi Direktori Kerja

Di terminal Codespaces, jalankan:

```bash
pwd
ls
```

Pastikan direktori aktif adalah root repo `DOAJ_Reviewer` (berisi `README.md`, `src`, `tests`).

Jika path default gagal, navigasi manual:

```bash
cd ~/workspaces/DOAJ_Reviewer
```

### 17.5 Menjalankan Server Simulasi

Jalankan perintah berikut dari root repo:

```bash
PYTHONPATH=src python3 -m doaj_reviewer.sim_server --host 0.0.0.0 --port 8787
```

Indikator berhasil:

```text
DOAJ Reviewer Simulation server running on http://0.0.0.0:8787
```

Terminal ini harus tetap aktif selama simulasi berjalan.

### 17.6 Membuka UI Simulasi

1. Buka panel `Ports` di Codespaces.
2. Temukan port `8787`.
3. Jika perlu, ubah visibility menjadi `Public`.
4. Klik `Open in Browser`.

Format URL umumnya:

- `https://<codespace-name>-8787.app.github.dev`

### 17.7 Menjalankan Simulasi dan Membaca Hasil

1. Isi field URL pada form simulasi.
2. Klik `Run simulation`.
3. Tinjau hasil:
   - overall result: `pass` / `fail` / `need_human_review`
   - per-rule notes
   - `Review URLs` untuk rule yang flagged
4. Gunakan tombol:
   - `Print to PDF`
   - `Download text`
   - `Reset form` untuk submission baru

### 17.8 Health Check Cepat

Jika UI tidak berjalan normal, cek server dari terminal:

```bash
curl -sS http://127.0.0.1:8787/api/health
```

Output normal:

```json
{"ok": true}
```

### 17.9 Troubleshooting Praktis

1. `HTTP ERROR 502`
- Penyebab umum: server tidak aktif.
- Tindakan: jalankan ulang perintah server.

2. Tombol `Run simulation` / `Reset form` tidak merespons
- Penyebab umum: browser masih memakai JavaScript versi lama (cache).
- Tindakan:
  - hard refresh (`Ctrl+F5` atau `Cmd+Shift+R`)
  - bila perlu stop + start server
  - buka ulang URL port dari panel `Ports`

3. `No module named doaj_reviewer`
- Penyebab umum: tidak berada di root repo atau lupa `PYTHONPATH=src`.
- Tindakan: pindah ke root repo dan ulangi command server lengkap.

4. Port `8787` tidak muncul
- Penyebab umum: proses server belum berhasil start.
- Tindakan: jalankan ulang command server, lalu refresh panel `Ports`.

5. Codespace berhenti otomatis
- Penyebab umum: idle timeout atau kuota.
- Tindakan: buka lagi Codespace dan jalankan server ulang.

### 17.10 Menghentikan Server

- Pada terminal server aktif, tekan `Ctrl + C`.

Jika port masih terpakai:

```bash
lsof -i :8787
kill <PID>
```

### 17.11 Rekomendasi Uji Kolaboratif

- Bagikan tautan repo, bukan URL runtime pribadi.
- Minta tiap kolega membuat Codespace sendiri.
- Dengan pola ini, pengujian lintas negara lebih stabil karena tidak tergantung satu sesi server.
