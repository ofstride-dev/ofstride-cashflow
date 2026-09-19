import { parseStringPromise } from 'xml2js';
import * as XLSX from 'xlsx';

const GSTIN_PATTERN = /^[0-9A-Z]{15}$/i;
const text = (value) => String(Array.isArray(value) ? value[0] ?? '' : value ?? '').trim();
const first = (value) => Array.isArray(value) ? value[0] : value;
const absoluteNumber = (value) => Math.abs(Number(String(value ?? 0).replace(/,/g, '')) || 0);

export function parseTallyDate(value) {
  const raw = text(value);
  if (!/^\d{8}$/.test(raw)) throw new Error(`Invalid Tally date: ${raw || 'empty'}`);
  const date = `${raw.slice(0, 4)}-${raw.slice(4, 6)}-${raw.slice(6, 8)}`;
  const parsed = new Date(`${date}T00:00:00.000Z`);
  if (Number.isNaN(parsed.getTime())) throw new Error(`Invalid Tally date: ${raw}`);
  return parsed.toISOString();
}

export function normalizeAmount(value, deemedPositive = '') {
  const amount = absoluteNumber(value);
  const isDeemedPositive = /^yes$/i.test(text(deemedPositive));
  return { amount, isDeemedPositive, direction: isDeemedPositive ? 'debit' : 'credit' };
}

function ledgerRecord(node) {
  const parent = text(node.PARENT);
  const entityType = /sundry creditors/i.test(parent) ? 'vendor' : /sundry debtors/i.test(parent) ? 'customer' : null;
  if (!entityType) return null;
  const gstin = text(node.PARTYGSTIN).toUpperCase();
  return { entity_name: text(node.LEDGERNAME), gstin: gstin || null, gstin_status: GSTIN_PATTERN.test(gstin) ? 'registered' : 'unregistered', entity_type: entityType, parent };
}

function nestedValue(node, names) {
  const wanted = new Set(names.map((name) => name.toUpperCase()));
  let result = '';
  const visit = (value) => {
    if (!value || typeof value !== 'object' || result) return;
    Object.entries(value).forEach(([name, child]) => {
      if (result) return;
      if (wanted.has(name.toUpperCase())) result = text(child);
      else if (child && typeof child === 'object') visit(child);
    });
  };
  visit(node);
  return result;
}

function partyLedgerRecord(node) {
  const entries = Array.isArray(node['ALLLEDGERENTRIES.LIST']) ? node['ALLLEDGERENTRIES.LIST'] : [];
  const partyEntry = entries.find((entry) => /^no$/i.test(text(entry.ISDEEMEDPOSITIVE)) && text(entry.PARTYLEDGERNAME || entry.LEDGERNAME));
  return text(partyEntry?.PARTYLEDGERNAME || partyEntry?.LEDGERNAME || node.PARTYLEDGERNAME || node.LEDGERNAME);
}

function partyGstinRecord(node, partyName) {
  const entries = Array.isArray(node['ALLLEDGERENTRIES.LIST']) ? node['ALLLEDGERENTRIES.LIST'] : [];
  const partyEntry = entries.find((entry) => text(entry.PARTYLEDGERNAME || entry.LEDGERNAME) === partyName);
  return text(partyEntry?.PARTYGSTIN || partyEntry?.GSTIN || node.PARTYGSTIN || node.GSTIN).toUpperCase();
}

function taxBreakdownRecord(node) {
  const tax = { igst_amount: 0, cgst_amount: 0, sgst_amount: 0 };
  const entries = Array.isArray(node['ALLLEDGERENTRIES.LIST']) ? node['ALLLEDGERENTRIES.LIST'] : [];
  entries.forEach((entry) => {
    const name = text(entry.LEDGERNAME || entry.PARTYLEDGERNAME).toLowerCase();
    const amount = absoluteNumber(first(entry.AMOUNT));
    if (name.includes('igst')) tax.igst_amount += amount;
    else if (name.includes('cgst')) tax.cgst_amount += amount;
    else if (name.includes('sgst')) tax.sgst_amount += amount;
  });
  return Object.fromEntries(Object.entries(tax).map(([key, value]) => [key, Number(value.toFixed(2))]));
}

function partyAmountRecord(node, partyName) {
  const entries = Array.isArray(node['ALLLEDGERENTRIES.LIST']) ? node['ALLLEDGERENTRIES.LIST'] : [];
  const partyEntry = entries.find((entry) => text(entry.PARTYLEDGERNAME || entry.LEDGERNAME) === partyName);
  return absoluteNumber(first(partyEntry?.AMOUNT));
}

function voucherRecord(node) {
  const voucherType = text(node.VOUCHERTYPENAME || node.VCHTYPE || node.$?.VCHTYPE).toLowerCase();
  if (!voucherType || !['sales', 'purchase', 'receipt', 'payment'].includes(voucherType)) return null;
  const allocations = Array.isArray(node['BILLALLOCATIONS.LIST']) ? node['BILLALLOCATIONS.LIST'] : collect(node, 'BILLALLOCATIONS.LIST');
  const allocationAmount = allocations.reduce((sum, allocation) => sum + absoluteNumber(first(allocation.AMOUNT)), 0);
  const deemedPositive = text(node.ISDEEMEDPOSITIVE);
  const dateValue = text(node.DATE || nestedValue(node, ['DATE']));
  const purchaseParty = partyLedgerRecord(node);
  const tax = taxBreakdownRecord(node);
  const amount = allocationAmount || partyAmountRecord(node, purchaseParty) || collect(node, 'AMOUNT').reduce((sum, value) => sum + absoluteNumber(first(value)), 0);
  return { invoice_id: text(node.VOUCHERNUMBER || nestedValue(node, ['VOUCHERNUMBER'])), remote_id: text(node.REMOTEID || node.GUID || nestedValue(node, ['REMOTEID', 'GUID'])), invoice_date: parseTallyDate(dateValue), total_amount: amount, taxable_value: Math.max(0, amount - tax.igst_amount - tax.cgst_amount - tax.sgst_amount), ...tax, amount_normalization: normalizeAmount(amount, deemedPositive), voucher_type: voucherType, cashflow_type: voucherType === 'receipt' ? 'Cash Collected' : voucherType === 'payment' ? 'Cash Disbursed' : voucherType, entity_name: purchaseParty, party_gstin: partyGstinRecord(node, purchaseParty), allocations: allocations.map((allocation) => ({ reference: text(allocation.NAME || allocation.BILLNAME || allocation.REFERENCE), amount: absoluteNumber(first(allocation.AMOUNT)), bill_type: text(allocation.BILLTYPE) || 'Agst Ref' })).filter((allocation) => allocation.reference) };
}

function collect(root, key) {
  const result = [];
  const visit = (value) => {
    if (!value || typeof value !== 'object') return;
    if (Array.isArray(value)) return value.forEach(visit);
    Object.entries(value).forEach(([name, child]) => {
      if (name.toUpperCase() === key) (Array.isArray(child) ? child : [child]).forEach((item) => result.push(item));
      visit(child);
    });
  };
  visit(root);
  return result;
}

export async function parseTallyXml(xml) {
  const root = await parseStringPromise(xml, { explicitArray: true, trim: true, normalizeTags: false });
  const ledgers = collect(root, 'LEDGER').map(ledgerRecord).filter(Boolean);
  const vouchers = collect(root, 'VOUCHER').map(voucherRecord).filter(Boolean);
  return { ledgers, vouchers };
}

export function parseTallyJson(value) {
  const source = typeof value === 'string' ? JSON.parse(value) : value;
  const ledgers = (source.ledgers || source.LEDGERS || []).map(ledgerRecord).filter(Boolean);
  const vouchers = (source.vouchers || source.VOUCHERS || []).map(voucherRecord).filter(Boolean);
  return { ledgers, vouchers };
}

export function parseTallyXlsx(buffer) {
  const workbook = XLSX.read(buffer, { type: 'buffer', cellDates: false });
  const rows = workbook.SheetNames.flatMap((sheetName) => XLSX.utils.sheet_to_json(workbook.Sheets[sheetName], { defval: '' }));
  return parseTallyJson({ vouchers: rows });
}

export async function parseTallyFile({ fileName, buffer }) {
  const extension = String(fileName).toLowerCase().split('.').pop();
  if (extension === 'xml') return parseTallyXml(buffer.toString('utf8'));
  if (extension === 'json') return parseTallyJson(buffer.toString('utf8'));
  if (extension === 'xlsx') return parseTallyXlsx(buffer);
  throw new Error('Only .xml, .json, and .xlsx Tally files are supported.');
}
