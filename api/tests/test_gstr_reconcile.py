from datetime import date

from gstr_reconcile import clean_invoice_number, match_exact, match_fuzzy, reconcile, total_tax


def book(number="INV/2026/01", tax=180.0):
    return {"supplier_gstin": "29ABCDE1234F1Z5", "invoice_number": number, "invoice_date": date(2026, 3, 1), "taxable_value": 1000.0, "cgst": tax / 2, "sgst": tax / 2, "igst": 0.0}


def portal(number="INV-2026-01", tax=180.0):
    return {"supplier_gstin": "29ABCDE1234F1Z5", "invoice_number": number, "invoice_date": date(2026, 3, 1), "taxable_value": 1000.0, "cgst": tax / 2, "sgst": tax / 2, "igst": 0.0}


def test_clean_and_exact_match():
    assert clean_invoice_number(" inv/2026-01 ") == "INV202601"
    result = reconcile([book()], [portal()])
    assert result["matched"][0]["tier"] == "MATCHED_EXACT"
    assert not result["missing_in_2b"] and not result["missing_in_books"]


def test_fuzzy_match_with_date_and_tax_tolerance():
    result = reconcile([book("INV-2026-001", 180)], [portal("INV-2026-00I", 188)])
    assert result["matched"][0]["tier"] == "MATCHED_FUZZY"


def test_tax_mismatch_is_terminal_bucket():
    result = reconcile([book(tax=180)], [portal(tax=300)])
    assert len(result["tax_mismatches"]) == 1
    assert not result["missing_in_2b"] and not result["missing_in_books"]