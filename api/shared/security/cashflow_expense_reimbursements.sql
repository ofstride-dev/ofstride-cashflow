-- Expense Portal accounting migration.
-- Accepted claim -> AP bill. Paid claim -> Cash Disbursed transaction.
-- Run once in the Supabase SQL Editor after the base cashflow/expense schema.
BEGIN;

-- Production still has the legacy category check. Expand it before changing rows.
ALTER TABLE public.expenses DROP CONSTRAINT IF EXISTS expenses_category_check;
ALTER TABLE public.expenses ADD CONSTRAINT expenses_category_check CHECK (category IN (
  'Meals & Entertainment', 'Travel & Transport', 'Travel Stay', 'Office Supplies',
  'Equipment & Hardware', 'Software & Subscriptions', 'Utilities & Telecom',
  'Repairs & Maintenance', 'Marketing & Promotion', 'Taxes & Compliance',
  'Health & Safety', 'Logistics & Courier', 'Other Operating Expenses',
  'Travel', 'Client Meals/Entertainment', 'Equipment/Hardware', 'Office/Misc', 'Uncategorized'
));

UPDATE public.expenses SET category = CASE category
  WHEN 'Travel' THEN 'Travel & Transport'
  WHEN 'Client Meals/Entertainment' THEN 'Meals & Entertainment'
  WHEN 'Equipment/Hardware' THEN 'Equipment & Hardware'
  WHEN 'Office/Misc' THEN 'Office Supplies'
  WHEN 'Uncategorized' THEN 'Other Operating Expenses'
  ELSE category END
WHERE category IN ('Travel', 'Client Meals/Entertainment', 'Equipment/Hardware', 'Office/Misc', 'Uncategorized');

ALTER TABLE public.expenses
  ADD COLUMN IF NOT EXISTS ap_bill_id UUID REFERENCES public.cashflow_bills(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS reimbursement_transaction_id UUID REFERENCES public.cashflow_transactions(id) ON DELETE SET NULL;

ALTER TABLE public.cashflow_transactions
  ADD COLUMN IF NOT EXISTS expense_id UUID REFERENCES public.expenses(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS employee_id UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS payable_account TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS expenses_ap_bill_id_key ON public.expenses(ap_bill_id) WHERE ap_bill_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS expenses_reimbursement_transaction_id_key ON public.expenses(reimbursement_transaction_id) WHERE reimbursement_transaction_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS cashflow_transactions_expense_reimbursement_key
  ON public.cashflow_transactions(expense_id)
  WHERE expense_id IS NOT NULL AND payment_mode = 'employee_reimbursement';

CREATE OR REPLACE FUNCTION public.ensure_expense_ap_bill(p_expense public.expenses)
RETURNS UUID LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
  v_entity UUID;
  v_bill UUID;
  v_name TEXT;
BEGIN
  IF p_expense.status NOT IN ('approved', 'ready_for_payment', 'paid') OR p_expense.ap_bill_id IS NOT NULL THEN
    RETURN p_expense.ap_bill_id;
  END IF;

  SELECT COALESCE(NULLIF(trim(full_name), ''), email, p_expense.user_id::text)
    INTO v_name FROM public.profiles WHERE id = p_expense.user_id;
  v_name := 'Employee Reimbursements - ' || COALESCE(v_name, p_expense.user_id::text);

  SELECT id INTO v_entity FROM public.cashflow_entities
   WHERE company_id = p_expense.company_id AND entity_type = 'vendor' AND name = v_name LIMIT 1;
  IF v_entity IS NULL THEN
    INSERT INTO public.cashflow_entities(company_id, name, entity_type)
    VALUES (p_expense.company_id, v_name, 'vendor') RETURNING id INTO v_entity;
  END IF;

  SELECT id INTO v_bill FROM public.cashflow_bills
   WHERE company_id = p_expense.company_id
     AND ocr_raw_data->>'source' = 'employee_expense'
     AND ocr_raw_data->>'expense_id' = p_expense.id::text LIMIT 1;
  IF v_bill IS NULL THEN
    INSERT INTO public.cashflow_bills
      (company_id, vendor_id, bill_number, bill_date, due_date, payment_terms_days,
       amount, status, ocr_raw_data, created_by)
    VALUES
      (p_expense.company_id, v_entity, 'EXP-' || left(p_expense.id::text, 12),
       p_expense.spend_date, p_expense.spend_date, 0, p_expense.amount,
       'approved', jsonb_build_object('source', 'employee_expense', 'expense_id', p_expense.id, 'employee_id', p_expense.user_id),
       p_expense.user_id)
    RETURNING id INTO v_bill;
  END IF;
  UPDATE public.expenses SET ap_bill_id = v_bill WHERE id = p_expense.id;
  RETURN v_bill;
END;
$$;

CREATE OR REPLACE FUNCTION public.sync_expense_accounting()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_bill UUID; v_transaction UUID;
BEGIN
  v_bill := public.ensure_expense_ap_bill(NEW);
  IF NEW.status = 'paid' THEN
    SELECT id INTO v_transaction FROM public.cashflow_transactions
     WHERE expense_id = NEW.id AND payment_mode = 'employee_reimbursement' LIMIT 1;
    IF v_transaction IS NULL THEN
      INSERT INTO public.cashflow_transactions
        (company_id, bill_id, transaction_date, amount, transaction_type,
         payment_mode, category, reference_no, created_by, expense_id,
         employee_id, payable_account)
      VALUES
        (NEW.company_id, v_bill, NEW.spend_date, NEW.amount, 'OUTFLOW',
         'employee_reimbursement', NEW.category, 'EXP-' || left(NEW.id::text, 12),
         NEW.user_id, NEW.id, NEW.user_id, 'Employee Reimbursements')
      RETURNING id INTO v_transaction;
    END IF;
    UPDATE public.expenses SET reimbursement_transaction_id = v_transaction WHERE id = NEW.id;
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS expense_accounting_sync ON public.expenses;
CREATE TRIGGER expense_accounting_sync
  AFTER INSERT OR UPDATE OF status ON public.expenses
  FOR EACH ROW EXECUTE FUNCTION public.sync_expense_accounting();

-- Preserve source petty-cash rows while migrating their history into claims.
INSERT INTO public.expenses
  (id, company_id, user_id, amount, currency, spend_date, category, description, status, created_at, updated_at)
SELECT p.id, p.company_id, p.recorded_by,
       COALESCE(NULLIF(p.cash_out, 0), p.cash_in), 'INR', p.entry_date,
       CASE p.category
         WHEN 'Travel' THEN 'Travel & Transport'
         WHEN 'Client Meals/Entertainment' THEN 'Meals & Entertainment'
         WHEN 'Equipment/Hardware' THEN 'Equipment & Hardware'
         WHEN 'Office/Misc' THEN 'Office Supplies'
         WHEN 'Uncategorized' THEN 'Other Operating Expenses'
         WHEN 'Meals & Entertainment' THEN 'Meals & Entertainment'
         WHEN 'Travel & Transport' THEN 'Travel & Transport'
         WHEN 'Travel Stay' THEN 'Travel Stay'
         WHEN 'Office Supplies' THEN 'Office Supplies'
         WHEN 'Equipment & Hardware' THEN 'Equipment & Hardware'
         WHEN 'Software & Subscriptions' THEN 'Software & Subscriptions'
         WHEN 'Utilities & Telecom' THEN 'Utilities & Telecom'
         WHEN 'Repairs & Maintenance' THEN 'Repairs & Maintenance'
         WHEN 'Marketing & Promotion' THEN 'Marketing & Promotion'
         WHEN 'Taxes & Compliance' THEN 'Taxes & Compliance'
         WHEN 'Health & Safety' THEN 'Health & Safety'
         WHEN 'Logistics & Courier' THEN 'Logistics & Courier'
         WHEN 'Other Operating Expenses' THEN 'Other Operating Expenses'
         ELSE 'Other Operating Expenses'
       END,
       p.description,
       CASE WHEN p.status = 'approved' THEN 'approved' ELSE 'submitted' END,
       p.created_at, p.created_at
FROM public.cashflow_petty_cash p
WHERE p.recorded_by IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM public.expenses e WHERE e.id = p.id);

-- Historical rows without recorded_by predate authenticated users and are
-- intentionally retained in cashflow_petty_cash as audit-only legacy data.
-- They cannot be converted into expenses because expenses.user_id is NOT NULL.

-- Fire accounting backfill for existing accepted/paid claims.
UPDATE public.expenses SET status = status
WHERE status IN ('approved', 'ready_for_payment', 'paid');

-- Enforce the standard categories after normalization.
ALTER TABLE public.expenses DROP CONSTRAINT IF EXISTS expenses_category_check;
ALTER TABLE public.expenses ADD CONSTRAINT expenses_category_check CHECK (category IN (
  'Meals & Entertainment', 'Travel & Transport', 'Travel Stay', 'Office Supplies',
  'Equipment & Hardware', 'Software & Subscriptions', 'Utilities & Telecom',
  'Repairs & Maintenance', 'Marketing & Promotion', 'Taxes & Compliance',
  'Health & Safety', 'Logistics & Courier', 'Other Operating Expenses'
));

COMMIT;