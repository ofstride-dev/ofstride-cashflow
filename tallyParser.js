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

function voucherRecord(node) {
  const voucherType = text(node.VOUCHERTYPENAME).toLowerCase();
  if (!voucherType) return null;
  const allocations = Array.isArray(node['BILLALLOCATIONS.LIST']) ? node['BILLALLOCATIONS.LIST'] : [];
  const amount = allocations.reduce((sum, allocation) => sum + absoluteNumber(first(allocation.AMOUNT)), 0);
  const deemedPositive = text(node.ISDEEMEDPOSITIVE);
  return { invoice_id: text(node.VOUCHERNUMBER), remote_id: text(node.REMOTEID || node.GUID), invoice_date: parseTallyDate(node.DATE), total_amount: amount, amount_normalization: normalizeAmount(amount, deemedPositive), voucher_type: voucherType, cashflow_type: voucherType === 'receipt' ? 'Cash Collected' : voucherType === 'payment' ? 'Cash Disbursed' : voucherType, entity_name: text(node.PARTYLEDGERNAME || node.LEDGERNAME), allocations: allocations.map((allocation) => ({ reference: text(allocation.NAME || allocation.BILLNAME || allocation.REFERENCE), amount: absoluteNumber(first(allocation.AMOUNT)), bill_type: text(allocation.BILLTYPE) || 'Agst Ref' })).filter((allocation) => allocation.reference) };
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
