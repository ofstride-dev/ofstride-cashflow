import { parseTallyFile } from './tallyParser.js';

const todayIso = () => new Date().toISOString().slice(0, 10);

export function createTallySyncController({ db, recalculateDashboard = async () => ({}) }) {
  return {
    async import(req, res) {
      try {
        const buffer = globalThis.Buffer.isBuffer(req.file?.buffer) ? req.file.buffer : globalThis.Buffer.from(req.body?.file_content_base64 || '', 'base64');
        if (!buffer.length) return res.status(400).json({ ok: false, error: 'A Tally file is required.' });
        const parsed = await parseTallyFile({ fileName: req.file?.originalname || req.body?.file_name, buffer });
        const companyId = req.tenant.companyId;
        let imported = 0; let updated = 0; let skipped = 0; let errors = 0;
        for (const ledger of parsed.ledgers) {
          await db('cashflow_entities').insert({ company_id: companyId, name: ledger.entity_name, entity_type: ledger.entity_type, gstin: ledger.gstin, bank_details: { tally_gstin_status: ledger.gstin_status } }).onConflict(['company_id', 'name', 'entity_type']).merge(['gstin', 'bank_details']);
        }
        for (const voucher of parsed.vouchers) {
          if (!voucher.invoice_id) { skipped += 1; continue; }
          const existing = await db('cashflow_tally_records').where({ company_id: companyId }).andWhere((query) => query.where({ invoice_id: voucher.invoice_id }).orWhere({ remote_id: voucher.remote_id })).first();
          const row = { company_id: companyId, invoice_id: voucher.invoice_id, remote_id: voucher.remote_id || null, voucher_type: voucher.voucher_type, voucher_date: voucher.invoice_date, total_amount: voucher.total_amount, direction: voucher.amount_normalization.direction, raw_data: voucher };
          if (existing) { await db('cashflow_tally_records').where({ id: existing.id }).update(row); updated += 1; } else { await db('cashflow_tally_records').insert(row); imported += 1; }
        }
        const dashboard = await recalculateDashboard(companyId, todayIso());
        return res.json({ ok: true, data: { imported, updated, skipped, errors, dashboard } });
      } catch (error) {
        return res.status(422).json({ ok: false, error: error instanceof Error ? error.message : 'Tally import failed.' });
      }
    },
  };
}
