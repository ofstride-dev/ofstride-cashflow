from abc import ABC, abstractmethod
from typing import Dict, Any

class InvoiceOCRInterface(ABC):
    @abstractmethod
    def extract_invoice_data(self, file_bytes: bytes, mime_type: str) -> Dict[str, Any]:
        """Extracts bill_number, gstin, amount, and line items from document."""
        pass

class MockInvoiceOCREngine(InvoiceOCRInterface):
    def extract_invoice_data(self, file_bytes: bytes, mime_type: str) -> Dict[str, Any]:
        # Phase-2 Interface Contract Placeholder
        return {
            "invoice_number": "MOCK-INV-001",
            "gstin": "29AAAAA0000A1Z5",
            "taxable_amount": 10000.00,
            "gst_amount": 1800.00,
            "total_amount": 11800.00,
            "confidence": 0.98
        }