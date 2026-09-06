import sqlite3

import pytest

from core.deals_v1 import generate, prepare_document, render_html


def sample(kind="invoice"):
    return {"kind": kind, "currency": "CAD", "title": "Engineering services",
            "client": "Synthetic test client", "terms": "Draft for review; no payment requested.",
            "items": [{"description": "Analysis", "quantity": "3", "unit_price": "0.10"}],
            "total": "999999"}


def test_exact_total_ignores_model_total():
    result = prepare_document(sample())
    assert result["total"] == "0.30"


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "-1", "1e8", True, 0.1, "1,20"])
def test_bad_amounts_rejected(amount):
    doc = sample()
    doc["items"][0]["unit_price"] = amount
    with pytest.raises(ValueError):
        prepare_document(doc)


def test_grouped_amount_and_rounding():
    doc = sample()
    doc["items"][0].update(quantity="1", unit_price="1,200.125")
    assert prepare_document(doc)["total"] == "1200.13"


def test_html_escaping():
    doc = sample()
    doc["client"] = '<script src="https://evil.invalid"></script>'
    markup = render_html(prepare_document(doc), "INV-TEST")
    assert "<script" not in markup
    assert "&lt;script" in markup
    assert "CYRYX LABS / ONYX" in markup


def test_pdf_and_durable_idempotency(tmp_path):
    from pypdf import PdfReader
    first = generate(sample(), output_dir=tmp_path, request_id="synthetic-1")
    again = generate(sample(), output_dir=tmp_path, request_id="synthetic-1")
    assert first == again
    assert first["delivered"] is False
    text = " ".join(page.extract_text() for page in PdfReader(first["path"]).pages)
    assert "0.30" in text and "CYRYX LABS" in text
    assert first["number"].endswith("00001")
    other = sample()
    other["title"] = "Changed"
    with pytest.raises(ValueError):
        generate(other, output_dir=tmp_path, request_id="synthetic-1")
    with sqlite3.connect(tmp_path / "onyx-deals.sqlite3") as db:
        assert db.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1


def test_separate_sequences_and_failure_receipt(tmp_path, monkeypatch):
    import core.deals_v1 as deals
    monkeypatch.setattr(deals, "_pdf_bytes", lambda _: b"%PDF synthetic test")
    assert generate(sample("quote"), output_dir=tmp_path, request_id="q")["number"].endswith("00001")
    assert generate(sample("proposal"), output_dir=tmp_path, request_id="p")["number"].endswith("00001")

    def fail(_):
        raise RuntimeError("renderer unavailable")
    monkeypatch.setattr(deals, "_pdf_bytes", fail)
    with pytest.raises(RuntimeError):
        generate(sample(), output_dir=tmp_path, request_id="fail")
    with sqlite3.connect(tmp_path / "onyx-deals.sqlite3") as db:
        assert db.execute("SELECT status FROM documents WHERE request_id='fail'").fetchone()[0] == "failed"
