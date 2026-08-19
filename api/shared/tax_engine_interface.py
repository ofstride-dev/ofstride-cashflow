from datetime import datetime, timedelta

def calculate_tds(amount: float, section: str) -> float:
    """Calculates Tax Deducted at Source (TDS) based on Indian IT Act."""
    tds_rates = {
        "194C_IND": 0.01,  # 1% for Individual Contractors
        "194C_CORP": 0.02, # 2% for Corporate Contractors
        "194J_TECH": 0.02, # 2% for Technical Services / Call Centers
        "194J_PROF": 0.10, # 10% for Professional Services
        "194I_RENT": 0.10, # 10% for Rent (Land/Building)
        "NONE": 0.0
    }
    rate = tds_rates.get(section, 0.0)
    return amount * rate

def calculate_msme_due_date(invoice_date_str: str, has_written_agreement: bool) -> str:
    """
    Section 43B(h): Calculates the absolute deadline to pay an MSME.
    15 days without an agreement, up to 45 days with an agreement.
    """
    try:
        inv_date = datetime.strptime(invoice_date_str, "%Y-%m-%d")
        days_allowed = 45 if has_written_agreement else 15
        due_date = inv_date + timedelta(days=days_allowed)
        return due_date.strftime("%Y-%m-%d")
    except ValueError:
        return ""