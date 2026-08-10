# Certificate PDF Generator — Capgemini Exceller AgentifAI Buildathon 2026

Generate one branded **PDF certificate per row** of an Excel sheet. The layout is
a faithful recreation of the supplied PowerPoint template (blue frame, white card,
Capgemini + AgentifAI Buildathon logos, award tier, recipient, dual signatures,
gradient accent bar and date).

Each output PDF is named **`{Messaging mailID}.pdf`**.

---

## 1. How it works

```
Excel row  ──►  Jinja2 fills certificate_template.html  ──►  headless Chromium prints ──►  output/{mailID}.pdf
```

- **pandas + openpyxl** read the Excel file.
- **Jinja2** injects the dynamic fields into `certificate_template.html`.
- Brand images are embedded as Base64 **data URIs**, so each certificate is fully
  self-contained (no external files or network needed at print time).
- **Playwright (Chromium)** prints the HTML to a pixel-accurate PDF at the exact
  slide size (10.833 in × 7.5 in).

Only three fields change per certificate — **Position**, **Candidate Name** and
**Team Name**. The recognition sentence is chosen from the Position (see
`config.json`).

---

## 2. Project structure

```
certificate_generator/
├── generate_certificates.py     # main script
├── certificate_template.html    # HTML/CSS certificate (Jinja2)
├── config.json                  # paths, column names, messages, date
├── requirements.txt
├── README.md
├── assets/
│   ├── logo_capgemini.png       # top-right logo
│   ├── logo_buildathon.png      # top-left logo
│   ├── gradient_bar.png         # bottom accent bar
│   ├── fonts/                   # Ubuntu / Ubuntu Medium / Ubuntu Bold (embedded)
│   │   ├── Ubuntu-Regular.ttf
│   │   ├── Ubuntu-Medium.ttf
│   │   └── Ubuntu-Bold.ttf
│   └── signatures/              # signatory images (replace with your own PNGs)
│       ├── sig_padmashree.png
│       └── sig_puneet.png
├── data/
│   └── certificates.xlsx        # your input (a sample is included)
└── output/                      # generated PDFs land here
```

The layout is reproduced from the source PowerPoint with the exact slide
coordinates, colours, the **Ubuntu** typeface (embedded in every PDF), the two
long-dashed signature lines and the straight bottom gradient bar.

---

## 3. Excel input format

The first sheet must contain these column headers (extra columns are ignored):

| Sr. No | Position | ssid | Candidate Name | Team Name | Messaging mailID |
|--------|----------|------|----------------|-----------|------------------|
| 1 | Winner | SS1001 | Aarav Sharma | Neural Nexus | aarav.sharma@example.com |
| 2 | 1st Runner Up | SS1002 | Diya Patel | Quantum Coders | diya.patel@example.com |
| 3 | 2nd Runner Up | SS1003 | Rohan Mehta | Team Innovate | rohan.mehta@example.com |
| 4 | Top 10 Finalist | SS1004 | Ananya Iyer | Code Catalysts | ananya.iyer@example.com |
| 5 | Top 100 Finalist | SS1005 | Kabir Singh | AI Avengers | kabir.singh@example.com |

- **Position** is printed as the large heading. Ordinals like `1st` / `2nd`
  are automatically superscripted (`1ˢᵗ`).
- **Team Name** may be left blank; the line is simply omitted.
- **Messaging mailID** becomes the file name — `aarav.sharma@example.com.pdf`.
  Duplicate mail ids are suffixed (`…_2.pdf`) so nothing is overwritten.
- Column header names can be remapped in `config.json` → `columns`.

---

## 4. Setup

Requires **Python 3.9+**.

```bash
cd certificate_generator
pip install -r requirements.txt

# download the Chromium browser Playwright uses (one time)
playwright install chromium
```

---

## 5. Run

```bash
python generate_certificates.py
```

Options:

```bash
python generate_certificates.py --excel data/certificates.xlsx --out output
python generate_certificates.py --config config.json
```

PDFs are written to the `output/` folder. Progress is logged per row.

---

## 6. Customising

Edit **`config.json`**:

- `certificate_date` — the date printed bottom-right.
- `messages.default` — the recognition sentence used for every tier…
- `messages.by_position` — …except positions listed here (e.g. *Top 100 Finalist*
  gets the participation message). Matching is exact first, then case-insensitive
  substring.
- `columns` — map to your own Excel header names.
- `signatories.left` / `signatories.right` — the two signatory **names**,
  **roles**, and **signature images**. Drop your own signature PNGs into
  `assets/signatures/` (transparent background works best) and point
  `signature_image` at them. Leave `signature_image` empty/absent to print just
  the dashed line with no image.
- `paths` — change input/output/asset/font locations.

Visual tweaks (fonts, colours, spacing, logos) live in
`certificate_template.html`. The palette taken from the template is:

| Purpose | Colour |
|---------|--------|
| Outer frame | `#016DB8` |
| Accent (heading / name) | `#0058AB` |
| Body text | `#121A38` |
| Card | `#FFFFFF` |

Replace the files in `assets/` to rebrand (keep the same file names, or update the
paths in `config.json`).

---

## 7. Troubleshooting

| Problem | Fix |
|---------|-----|
| `Executable doesn't exist … chrome-headless-shell` | Run `playwright install chromium`. |
| Locked-down machine with a pre-installed browser | Set `PLAYWRIGHT_CHROMIUM_PATH=/path/to/chrome` (or `chromium_executable` in `config.json`) to skip the download. |
| `Excel is missing required column(s)` | Header names don't match — fix the sheet or the `columns` map in `config.json`. |
| Row skipped | The row had no Candidate Name or no mail id — those are required. |
| Fonts look different | The **Ubuntu** fonts in `assets/fonts/` are embedded into each PDF, so output is identical everywhere. If you delete them, the script falls back to a generic sans-serif. |
| Signature image missing | Check the `signature_image` path in `config.json`; a missing file is skipped with a warning (the dashed line still prints). |
| PDF has margins / wrong size | Don't change `@page`/`pdf` sizes; they are fixed to the slide dimensions. |
```
