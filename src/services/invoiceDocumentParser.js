import * as XLSX from 'xlsx';

const toNumber = (value, fallback = 0) => {
  const parsed = Number(String(value ?? '').replace(/[,₹]/g, '').trim());
  return Number.isFinite(parsed) ? parsed : fallback;
};

const valueFor = (row, names) => {
  const keys = Object.keys(row || {});
  const key = keys.find((candidate) => names.some((name) => candidate.toLowerCase().replace(/[^a-z0-9]/g, '').includes(name)));
  return key ? row[key] : undefined;
};

export async function parseInvoiceSpreadsheet(file) {
  const workbook = XLSX.read(await file.arrayBuffer(), { type: 'array' });
  const rows = workbook.SheetNames.flatMap((sheetName) => XLSX.utils.sheet_to_json(workbook.Sheets[sheetName], { defval: '' }));
  const lineItems = rows.map((row) => {
    const itemName = String(valueFor(row, ['itemname', 'description', 'particular', 'product', 'item']) || '').trim();
    const unitPrice = toNumber(valueFor(row, ['unitprice', 'price', 'rate', 'unitrate']));
    const quantity = toNumber(valueFor(row, ['quantity', 'qty']), 1) || 1;
    const discount = Math.min(100, Math.max(0, toNumber(valueFor(row, ['discountpercent', 'discount']))));
    const lineTotal = toNumber(valueFor(row, ['linetotal', 'totalprice', 'total', 'amount']), unitPrice * quantity * (1 - discount / 100));
    return { itemName, description: itemName, unitPrice, quantity, discount, lineTotal: Number(lineTotal.toFixed(3)) };
  }).filter((item) => item.itemName || item.unitPrice || item.lineTotal);

  const first = rows[0] || {};
  return {
    vendor_name: String(valueFor(first, ['vendorname', 'supplier', 'vendor']) || '').trim(),
    customer_name: String(valueFor(first, ['customername', 'customer', 'buyer']) || '').trim(),
    vendor_gstin: String(valueFor(first, ['vendorgstin', 'suppliergstin', 'gstin']) || '').trim(),
    customer_gstin: String(valueFor(first, ['customergstin', 'buyergstin']) || '').trim(),
    bill_number: String(valueFor(first, ['billnumber', 'invoicenumber', 'invoiceid']) || '').trim(),
    invoice_number: String(valueFor(first, ['invoicenumber', 'billnumber', 'invoiceid']) || '').trim(),
    bill_date: String(valueFor(first, ['billdate', 'invoicedate', 'date']) || '').trim(),
    invoice_date: String(valueFor(first, ['invoicedate', 'billdate', 'date']) || '').trim(),
    parsedLineItems: lineItems,
  };
}
