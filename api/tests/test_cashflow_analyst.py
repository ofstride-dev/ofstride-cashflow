"""Pure regression tests for the read-only financial analyst helpers."""

import unittest
from datetime import date

from cashflow_analyst import (
    _deterministic_answer,
    _resolve_range,
    _select_prompt_evidence,
    _validated_model_fields,
)


class CashflowAnalystTests(unittest.TestCase):
    def test_custom_range_is_preserved(self):
        start, end, period = _resolve_range({"start_date": "2026-01-02", "end_date": "2026-01-09"})
        self.assertEqual(start, date(2026, 1, 2))
        self.assertEqual(end, date(2026, 1, 9))
        self.assertEqual(period, "custom")

    def test_invalid_custom_range_is_rejected(self):
        with self.assertRaises(ValueError):
            _resolve_range({"start_date": "2026-02-01", "end_date": "2026-01-01"})

    def _evidence(self):
        return {
            "metrics": {
                "cash_inflow": 1250.0,
                "cash_outflow": 800.0,
                "net_movement": 450.0,
                "pending_receivables": 2000.0,
                "open_payables": 700.0,
                "invoice_revenue": 5000.0,
                "collected_revenue": 1250.0,
                "bill_commitments": 900.0,
                "transaction_count": 4,
                "pending_invoice_count": 2,
                "open_bill_count": 1,
                "petty_cash_inflow": 50.0,
                "petty_cash_outflow": 25.0,
            }
        }

    def test_earnings_answer_uses_invoice_revenue(self):
        result = _deterministic_answer("ask", self._evidence(), "How much did we earn?")
        self.assertIn("₹5,000.00", result["answer"])
        self.assertIn("₹1,250.00", result["answer"])
        self.assertNotEqual(result["answer"], _deterministic_answer("explain_movement", self._evidence())["answer"])

    def test_intents_produce_different_answers(self):
        evidence = self._evidence()
        answers = {
            intent: _deterministic_answer(intent, evidence, question)["answer"]
            for intent, question in (
                ("summary", ""),
                ("report", ""),
                ("explain_movement", ""),
                ("explain_metric", "accounts payable"),
                ("ask", "How much did we earn?"),
            )
        }
        self.assertEqual(len(set(answers.values())), len(answers))

    def test_deterministic_answer_uses_authoritative_totals(self):
        result = _deterministic_answer("summary", self._evidence())
        self.assertIn("₹1,250.00", result["answer"])
        self.assertIn("₹800.00", result["answer"])
        self.assertIn("₹450.00", result["headline"])
        self.assertTrue(result["risks"])

    def test_prompt_evidence_is_intent_specific(self):
        evidence = self._evidence() | {
            "period": {"start_date": "2026-01-01", "end_date": "2026-01-31"},
            "sources": ["dashboard", "transactions", "accounts_payable", "accounts_receivable"],
            "unavailable": [],
            "dashboard": {"summary": [{"cash": 1}], "trend": [{"month": "2026-01"}]},
            "transactions": [{"amount": 2}],
            "accounts_payable": [{"amount": 3}],
            "accounts_receivable": [{"amount": 4}],
        }
        selected = _select_prompt_evidence("explain_metric", "show accounts payable", evidence)
        self.assertIn("accounts_payable", selected)
        self.assertNotIn("accounts_receivable", selected)
        self.assertEqual(selected["metrics"], evidence["metrics"])

        summary = _select_prompt_evidence("summary", "", evidence)
        self.assertEqual(summary["dashboard"]["summary"], [{"cash": 1}])

    def test_malformed_model_fields_fall_back(self):
        fallback = {"headline": "Safe headline", "answer": "Safe answer", "findings": ["fact"], "risks": [], "actions": ["review"]}
        result = _validated_model_fields({"headline": 12, "answer": "  Better answer ", "findings": ["ok", 4], "risks": "bad"}, fallback)
        self.assertEqual(result["headline"], fallback["headline"])
        self.assertEqual(result["answer"], "Better answer")
        self.assertEqual(result["findings"], fallback["findings"])
        self.assertEqual(result["risks"], fallback["risks"])


if __name__ == "__main__":
    unittest.main()