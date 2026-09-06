"""Local Onyx invoice/quote/proposal generation; never sends or collects payment."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

from memory.obsidian_v1 import _checked
from memory.store import contains_secret

KINDS = {"invoice": "INV", "quote": "QUO", "proposal": "PRO"}


def _text(value, name, maximum=2000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"Invalid {name}")
    if any(ord(char) < 32 and char not in "\n\t" for char in value) or contains_secret(value):
        raise ValueError(f"Unsafe {name}")
    return value.strip()


def _number(value):
    # Reject locale ambiguity, exponent notation, NaN/Infinity and binary floats.
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise ValueError("Amounts must be exact decimal strings or integers")
    raw = str(value).strip()
    if not re.fullmatch(r"(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d{1,4})?", raw):
        raise ValueError("Use decimal-point amounts, optionally comma-grouped")
    try:
        result = Decimal(raw.replace(",", ""))
    except InvalidOperation as exc:
        raise ValueError("Invalid amount") from exc
    if not result.is_finite() or result < 0 or result > Decimal("1000000000"):
        raise ValueError("Amount outside supported bounds")
    return result


def prepare_document(raw):
    if not isinstance(raw, dict) or raw.get("kind") not in KINDS:
        raise ValueError("Choose invoice, quote or proposal")
    currency = raw.get("currency", "")
    if currency not in {"USD", "CAD", "EUR", "GBP", "BRL"}:
        raise ValueError("Explicit supported currency required")
    items = raw.get("items")
    if not isinstance(items, list) or not 1 <= len(items) <= 100:
        raise ValueError("Provide 1 to 100 line items")
    lines = []
    total = Decimal(0)
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Invalid line item")
        quantity, unit = _number(item.get("quantity")), _number(item.get("unit_price"))
        if quantity <= 0:
            raise ValueError("Quantity must be positive")
        amount = (quantity * unit).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if amount > Decimal("1000000000"):
            raise ValueError("Line amount exceeds supported bounds")
        total += amount
        lines.append({"description": _text(item.get("description"), "description", 500),
                      "quantity": str(quantity), "unit_price": str(unit), "amount": str(amount)})
    if total > Decimal("1000000000"):
        raise ValueError("Document total exceeds supported bounds")
    # No invented taxes, rates, bank details or deadlines. Caller supplies terms.
    return {"kind": raw["kind"], "currency": currency,
            "title": _text(raw.get("title"), "title", 200),
            "client": _text(raw.get("client"), "client", 300),
            "terms": _text(raw.get("terms"), "terms"),
            "items": lines, "total": str(total.quantize(Decimal("0.01")))}


def render_html(document, number):
    def escape(value):
        return html.escape(str(value), quote=True)
    rows = "".join("<tr>" + "".join(f"<td>{escape(line[key])}</td>" for key in
                   ("description", "quantity", "unit_price", "amount")) + "</tr>"
                   for line in document["items"])
    return f"""<!doctype html><html lang="en"><meta charset="utf-8">
<title>{escape(number)} — Onyx</title><style>
@page {{ size:A4; margin:18mm; }}
body {{font:14px 'Segoe UI',Arial,sans-serif;color:#172529;background:#fff}}
header {{border-bottom:3px solid #008c91;padding-bottom:18px;letter-spacing:2px}}
h1 {{font-size:28px;letter-spacing:0}} small {{color:#42595b}}
table {{width:100%;border-collapse:collapse;margin:28px 0}}
td,th {{border-bottom:1px solid #d7e0e0;padding:12px 8px;text-align:right}}
td:first-child,th:first-child {{text-align:left;overflow-wrap:anywhere}}
thead {{display:table-header-group}} tr {{break-inside:avoid}}
.terms {{white-space:pre-wrap;overflow-wrap:anywhere}} footer {{margin-top:32px;color:#42595b}}
</style><header>CYRYX LABS / ONYX</header>
<h1>{escape(document['title'])}</h1><small>{escape(number)} · {escape(document['kind'].title())}</small>
<p>Prepared for {escape(document['client'])}</p>
<table><thead><tr><th>Description</th><th>Quantity</th><th>Unit price</th><th>Amount</th></tr></thead>
<tbody>{rows}</tbody></table><h2>Total: {escape(document['currency'])} {escape(document['total'])}</h2>
<h3>Terms</h3><div class="terms">{escape(document['terms'])}</div>
<footer>Prepared with Onyx · Cyryx Labs. Not a payment receipt.</footer></html>"""


def _pdf_bytes(markup):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True)
        try:
            page = browser.new_page(java_script_enabled=False)
            page.route("**/*", lambda route: route.abort())
            page.set_content(markup, wait_until="load", timeout=15000)
            return page.pdf(print_background=True, prefer_css_page_size=True)
        finally:
            browser.close()


def generate(raw, *, output_dir: Path, request_id: str):
    """Owner CLI operation. Durable number reservation; no network delivery."""
    request_id = _text(request_id, "request id", 120)
    document = prepare_document(raw)
    root = _checked(output_dir)
    if not root.is_dir() or root == Path(root.anchor):
        raise ValueError("Select an existing output directory")
    ledger = root / "onyx-deals.sqlite3"
    for candidate in (ledger, *(Path(str(ledger) + suffix) for suffix in ("-wal", "-shm", "-journal"))):
        if candidate.exists() or candidate.is_symlink():
            _checked(candidate)
    digest = hashlib.sha256(json.dumps(document, sort_keys=True).encode()).hexdigest()
    with sqlite3.connect(ledger, timeout=10) as db:
        db.execute("PRAGMA synchronous=FULL")
        db.execute("CREATE TABLE IF NOT EXISTS documents (request_id TEXT PRIMARY KEY, digest TEXT NOT NULL, "
                   "number TEXT UNIQUE NOT NULL, status TEXT NOT NULL, pdf_digest TEXT)")
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute("SELECT digest,number,status,pdf_digest FROM documents WHERE request_id=?",
                              (request_id,)).fetchone()
        if existing:
            if existing[0] != digest:
                raise ValueError("Request id already belongs to a different document")
            target = _checked(root / f"{existing[1]}.pdf")
            if existing[2] != "generated" or hashlib.sha256(target.read_bytes()).hexdigest() != existing[3]:
                raise ValueError("Previous generation requires reconciliation; no duplicate number issued")
            return {"status": "generated", "number": existing[1], "path": str(target), "delivered": False}
        prefix = f"{KINDS[document['kind']]}-{datetime.now(timezone.utc).year}-"
        count = db.execute("SELECT COUNT(*) FROM documents WHERE number LIKE ?", (prefix + "%",)).fetchone()[0]
        number = f"{prefix}{count + 1:05d}"
        db.execute("INSERT INTO documents VALUES(?,?,?,'reserved',NULL)", (request_id, digest, number))
        db.commit()  # A crash preserves the reservation rather than duplicating it.
        target = root / f"{number}.pdf"
        try:
            content = _pdf_bytes(render_html(document, number))
            _checked(root)
            with target.open("xb") as stream:
                stream.write(content)
            db.execute("UPDATE documents SET status='generated', pdf_digest=? WHERE request_id=?",
                       (hashlib.sha256(content).hexdigest(), request_id))
        except Exception:
            db.execute("UPDATE documents SET status='failed' WHERE request_id=?", (request_id,))
            db.commit()
            raise
    return {"status": "generated", "number": number, "path": str(target), "delivered": False}


def generate_for_assistant(document_json: str, request_id: str):
    """Called only after the host's exact-argument owner confirmation."""
    from core.paths import private_control_plane_runtime_dir
    if not isinstance(document_json, str) or len(document_json.encode("utf-8")) > 128 * 1024:
        raise ValueError("Document JSON exceeds its bound")
    document = json.loads(document_json)
    prepare_document(document)
    output = private_control_plane_runtime_dir().parent / "Business Documents"
    ancestor = output
    while not ancestor.exists():
        ancestor = ancestor.parent
    _checked(ancestor)
    output.mkdir(parents=True, exist_ok=True)
    _checked(output)
    return generate(document, output_dir=output, request_id=request_id)


def cli(argv=None):
    parser = argparse.ArgumentParser(description="Onyx local business documents (no delivery)")
    parser.add_argument("input", type=Path, help="Owner-approved structured JSON, max 128 KiB")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--request-id", required=True)
    args = parser.parse_args(argv)
    try:
        with args.input.open("rb") as source:
            data = source.read(128 * 1024 + 1)
        if len(data) > 128 * 1024:
            raise ValueError("Input too large")
        print(json.dumps(generate(json.loads(data), output_dir=args.output_dir, request_id=args.request_id)))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": type(exc).__name__}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(cli())
