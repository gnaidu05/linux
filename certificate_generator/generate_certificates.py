#!/usr/bin/env python3
"""
Certificate PDF generator for the Capgemini Exceller AgentifAI Buildathon 2026.

Reads recipient data from an Excel file, renders each row into an HTML
certificate using a Jinja2 template (a faithful recreation of the supplied
PowerPoint layout), and exports each certificate as a PDF via headless
Chromium (Playwright). One PDF is produced per row, named "{mailID}.pdf".

Expected Excel columns (header names are configurable in config.json):

    Sr. No | Position | ssid | Candidate Name | Team Name | Messaging mailID

Dynamic parts of the certificate:  Position, Candidate Name, Team Name.
The recognition message is chosen from the Position (see config.json).

Usage:
    python generate_certificates.py
    python generate_certificates.py --excel data/certificates.xlsx --out output
    python generate_certificates.py --config config.json

Setup (once):
    pip install -r requirements.txt
    playwright install chromium
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import logging
import mimetypes
import os
import re
import sys
from pathlib import Path

import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import sync_playwright

# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("certificates")

# Superscript rendering for ordinal award tiers ("1st Runner Up" -> 1ˢᵗ ...)
ORDINAL_RE = re.compile(r"\b(\d+)(st|nd|rd|th)\b", flags=re.IGNORECASE)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def load_config(config_path: Path) -> dict:
    with config_path.open(encoding="utf-8") as fh:
        return json.load(fh)


def data_uri(path: Path) -> str:
    """Embed a local image as a Base64 data URI so the HTML is self-contained."""
    if not path.is_file():
        raise FileNotFoundError(f"Asset not found: {path}")
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def font_uri(path: Path) -> str:
    """Embed a local TrueType font as a Base64 data URI for @font-face."""
    if not path.is_file():
        raise FileNotFoundError(f"Font not found: {path}")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:font/ttf;base64,{encoded}"


def optional_uri(path: Path):
    """Data URI for an optional asset; None (with a warning) if it is missing."""
    if not path.is_file():
        log.warning("Optional asset missing, skipping: %s", path)
        return None
    return data_uri(path)


def safe_filename(name: str) -> str:
    """Turn an arbitrary string (mail id) into a safe file stem."""
    name = str(name).strip()
    # keep the readable local/domain parts but strip anything unsafe for a path
    name = re.sub(r"[^A-Za-z0-9._@+\-]", "_", name)
    return name or "certificate"


def clean(value) -> str:
    """Normalise a cell value to a trimmed string ('' for NaN/None)."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if pd.isna(value):
        return ""
    return str(value).strip()


def position_to_html(position: str) -> str:
    """Escape the position and superscript any ordinal suffix (st/nd/rd/th)."""
    escaped = html.escape(position)
    return ORDINAL_RE.sub(r"\1<sup>\2</sup>", escaped)


def message_for(position: str, messages: dict) -> str:
    """Pick the recognition message for a given position, else the default."""
    by_position = messages.get("by_position", {})
    # exact match first, then case-insensitive / substring match
    if position in by_position:
        return by_position[position]
    for key, text in by_position.items():
        if key.lower() in position.lower():
            return text
    return messages.get("default", "")


def require_columns(df: pd.DataFrame, columns: dict) -> None:
    missing = [name for name in columns.values() if name not in df.columns]
    if missing:
        raise KeyError(
            "Excel is missing required column(s): "
            + ", ".join(repr(m) for m in missing)
            + f"\nColumns found: {list(df.columns)}"
        )


# --------------------------------------------------------------------------- #
# Core generation
# --------------------------------------------------------------------------- #
def generate(config: dict, base_dir: Path,
             excel_override: str | None = None,
             out_override: str | None = None) -> int:
    paths = config["paths"]
    cols = config["columns"]

    excel_file = base_dir / (excel_override or paths["excel_file"])
    output_dir = base_dir / (out_override or paths["output_dir"])
    template_file = base_dir / paths["template_file"]
    output_dir.mkdir(parents=True, exist_ok=True)

    # Embed brand assets, fonts and signatories once (shared by every cert).
    assets = paths["assets"]
    fonts = paths["fonts"]
    sig = config.get("signatories", {})
    sig_left = sig.get("left", {})
    sig_right = sig.get("right", {})

    def sig_uri(entry):
        img = entry.get("signature_image")
        return optional_uri(base_dir / img) if img else None

    shared = {
        "logo_capgemini": data_uri(base_dir / assets["logo_capgemini"]),
        "logo_buildathon": data_uri(base_dir / assets["logo_buildathon"]),
        "gradient_bar": data_uri(base_dir / assets["gradient_bar"]),
        "font_regular": font_uri(base_dir / fonts["regular"]),
        "font_medium": font_uri(base_dir / fonts["medium"]),
        "font_bold": font_uri(base_dir / fonts["bold"]),
        "sig_left_name": sig_left.get("name", ""),
        "sig_left_role": sig_left.get("role", ""),
        "sig_left_img": sig_uri(sig_left),
        "sig_right_name": sig_right.get("name", ""),
        "sig_right_role": sig_right.get("role", ""),
        "sig_right_img": sig_uri(sig_right),
        "date": config.get("certificate_date", ""),
    }

    # Read the Excel data.
    log.info("Reading %s", excel_file)
    df = pd.read_excel(excel_file, sheet_name=paths.get("sheet_name", 0),
                       dtype=str, engine="openpyxl")
    df = df.dropna(how="all")
    require_columns(df, cols)
    log.info("Loaded %d row(s)", len(df))

    # Jinja2 template environment.
    env = Environment(
        loader=FileSystemLoader(str(template_file.parent)),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template(template_file.name)

    pdf_w = f'{config["pdf"]["width_inches"]}in'
    pdf_h = f'{config["pdf"]["height_inches"]}in'
    messages = config.get("messages", {})

    ok, skipped = 0, 0
    seen: dict[str, int] = {}

    # Optional explicit Chromium path. Normal users can leave this unset and
    # rely on `playwright install chromium`; set it (env var or config) only in
    # locked-down environments that ship a pre-installed browser.
    chromium_exe = os.environ.get("PLAYWRIGHT_CHROMIUM_PATH") \
        or config.get("chromium_executable") or None
    launch_kwargs = {"executable_path": chromium_exe} if chromium_exe else {}
    if chromium_exe:
        log.info("Using Chromium at %s", chromium_exe)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(**launch_kwargs)
        page = browser.new_page()

        for idx, row in df.iterrows():
            position = clean(row[cols["position"]])
            candidate = clean(row[cols["candidate_name"]])
            team = clean(row[cols["team_name"]])
            mail = clean(row[cols["mail_id"]])

            row_no = idx + 2  # +2 => account for header row + 1-based
            if not candidate or not mail:
                log.warning("Row %s: missing candidate name or mail id -> skipped",
                            row_no)
                skipped += 1
                continue

            # Guard against duplicate mail ids overwriting each other.
            stem = safe_filename(mail)
            seen[stem] = seen.get(stem, 0) + 1
            if seen[stem] > 1:
                stem = f"{stem}_{seen[stem]}"
                log.warning("Row %s: duplicate mail id -> saving as %s.pdf",
                            row_no, stem)

            rendered = template.render(
                position_html=position_to_html(position),
                candidate_name=candidate,
                team_name=team,
                message=message_for(position, messages),
                **shared,
            )

            page.set_content(rendered, wait_until="networkidle")
            out_pdf = output_dir / f"{stem}.pdf"
            page.pdf(
                path=str(out_pdf),
                width=pdf_w,
                height=pdf_h,
                print_background=True,
                margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
            )
            ok += 1
            log.info("[%d/%d] %-22s -> %s", ok, len(df), position or "-",
                     out_pdf.name)

        browser.close()

    log.info("Done. %d generated, %d skipped. Output: %s", ok, skipped, output_dir)
    return ok


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def main() -> None:
    parser = argparse.ArgumentParser(description="Generate certificate PDFs from Excel.")
    parser.add_argument("--config", default="config.json", help="Path to config.json")
    parser.add_argument("--excel", help="Override the Excel input path")
    parser.add_argument("--out", help="Override the output directory")
    args = parser.parse_args()

    base_dir = Path(__file__).resolve().parent
    config_path = (base_dir / args.config) if not Path(args.config).is_absolute() \
        else Path(args.config)

    try:
        config = load_config(config_path)
        count = generate(config, base_dir, args.excel, args.out)
    except FileNotFoundError as exc:
        log.error("%s", exc)
        sys.exit(1)
    except KeyError as exc:
        log.error("%s", str(exc).strip('"'))
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001 - surface a clean message to the user
        log.error("Generation failed: %s", exc)
        sys.exit(1)

    if count == 0:
        log.warning("No certificates were generated - check your Excel data.")
        sys.exit(2)


if __name__ == "__main__":
    main()
