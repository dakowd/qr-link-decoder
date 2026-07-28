"""
Reads redirect links from the first column of a spreadsheet (CSV, XLS, or
XLSX). Each link redirects to a QR code image; this script follows the
redirect, decodes the QR code, and writes the decoded text into a "QR code"
column.

Usage:
    python main.py input.csv|.xls|.xlsx [output.csv|.xls|.xlsx]

If output is omitted, the input file is updated in place (a .bak backup is
written first). Rows that already have a value in the QR code column are
skipped, so the script can be re-run safely to pick up rows that failed
before.

Note: writing legacy .xls is not supported (the format is effectively
retired). If no output path is given and the input is .xls, results are
written to a sibling .xlsx file instead.
"""

import sys
import shutil
import time
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
import requests

try:
    from pyzbar.pyzbar import decode as zbar_decode
except (ImportError, OSError):
    zbar_decode = None

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}
QR_COL_NAME = "QR code"
REQUEST_TIMEOUT = 15
RETRY_COUNT = 2
RETRY_DELAY = 2

READ_ENGINES = {".xlsx": "openpyxl", ".xls": "xlrd"}


def decode_qr(image_bytes):
    data = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        return None

    text, _, _ = cv2.QRCodeDetector().detectAndDecode(img)
    if text:
        return text

    if zbar_decode is not None:
        results = zbar_decode(img)
        if results:
            return results[0].data.decode("utf-8", errors="replace")

    return None


def fetch_qr_text(url, session):
    last_error = None
    for attempt in range(1, RETRY_COUNT + 1):
        try:
            resp = session.get(
                url, headers=HEADERS, timeout=REQUEST_TIMEOUT, allow_redirects=True
            )
            resp.raise_for_status()
            text = decode_qr(resp.content)
            if text:
                return text, None
            return None, "QR code not detected in image"
        except requests.RequestException as exc:
            last_error = str(exc)
            if attempt < RETRY_COUNT:
                time.sleep(RETRY_DELAY)
    return None, last_error or "request failed"


def read_table(path):
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path, dtype=str, keep_default_na=False)
    if suffix in READ_ENGINES:
        return pd.read_excel(
            path, dtype=str, keep_default_na=False, engine=READ_ENGINES[suffix]
        )
    raise ValueError(f"Unsupported file type: {suffix} (use .csv, .xls, or .xlsx)")


def write_table(df, path):
    suffix = path.suffix.lower()
    if suffix == ".csv":
        df.to_csv(path, index=False)
    elif suffix == ".xlsx":
        df.to_excel(path, index=False, engine="openpyxl")
    elif suffix == ".xls":
        raise ValueError("Writing .xls is not supported; use .xlsx instead")
    else:
        raise ValueError(f"Unsupported file type: {suffix} (use .csv, .xls, or .xlsx)")


def main():
    if len(sys.argv) < 2:
        print("Usage: python main.py <input.csv|.xls|.xlsx> [output.csv|.xls|.xlsx]")
        sys.exit(1)

    input_path = Path(sys.argv[1])
    if not input_path.exists():
        print(f"File not found: {input_path}")
        sys.exit(1)

    if len(sys.argv) > 2:
        output_path = Path(sys.argv[2])
    elif input_path.suffix.lower() == ".xls":
        output_path = input_path.with_suffix(".xlsx")
        print(f"Note: .xls can't be written back to; saving results to {output_path}")
    else:
        output_path = input_path

    if output_path == input_path:
        backup_path = input_path.with_suffix(input_path.suffix + ".bak")
        shutil.copy2(input_path, backup_path)
        print(f"Backup written to {backup_path}")

    df = read_table(input_path)
    if df.shape[1] < 1:
        print("The file has no columns to read links from.")
        sys.exit(1)

    link_col = df.columns[0]
    if QR_COL_NAME not in df.columns:
        df[QR_COL_NAME] = ""

    session = requests.Session()

    total = len(df)
    processed = 0
    failed = 0

    for i, row in df.iterrows():
        url = str(row[link_col]).strip()
        if not url:
            continue

        if str(row[QR_COL_NAME]).strip():
            continue  # already processed, skip (safe to re-run)

        print(f"[{i + 1}/{total}] {url} ...", end=" ", flush=True)
        text, error = fetch_qr_text(url, session)

        if text:
            df.at[i, QR_COL_NAME] = text
            print("OK")
            processed += 1
        else:
            df.at[i, QR_COL_NAME] = f"ERROR: {error}"
            print(f"FAILED ({error})")
            failed += 1

        write_table(df, output_path)  # save after each row so progress isn't lost

    print(f"\nDone. {processed} decoded, {failed} failed. Saved to {output_path}")


if __name__ == "__main__":
    main()
