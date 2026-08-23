# OfStride Cashflow — Product Requirements Document

**Document status:** Repository-derived baseline  
**Scope:** Current implementation in this repository  
**Generated:** 2026-08-20

> This document describes behavior evidenced by the source code, configuration, SQL migrations, and frontend routes in the repository. Where intent is not explicit, the text labels an architectural assumption rather than presenting it as a confirmed requirement.

## 1. Executive Summary

OfStride Cashflow is a multi-tenant finance workspace for small and medium businesses. It gives authenticated workspace members a single frontend for:

- Accounts payable (vendor bills and approval)
- Accounts receivable (customer invoices, collection, and approval)
- Payments and transaction records
- Petty-cash entries and approval
- Cashflow dashboard reporting
- Bank-statement parsing and reconciliation
- Workspace invitations and membership
- Existing employee-expense workflows inherited from the broader OfStride application

The product addresses fragmented finance administration by centralizing operational records, applying company-level authorization, and comparing bank transactions with platform-side AP, AR, and petty-cash records. The intended outcome is better visibility into cash inflow/outflow, fewer manual reconciliation steps, and safer collaboration between owners, finance users, administrators, and employees.

The repository contains two related Azure Functions applications:

1. `api/` — the primary application API, including Cashflow modules and shared platform services.
2. `comms-api/` — a separate communications deployment for invitations, career notifications, and contact notifications.

The frontend is a Vite React single-page application backed by Supabase Auth and Supabase database RPC/table access. Cashflow routes are available under both concise paths such as `/dashboard` and namespaced compatibility paths such as `/cashflow/dashboard`.

### Product boundary

Cashflow is the primary product surface documented here. The repository also includes careers, resume-builder, retrieval, orchestration, and employee-expense code. Those capabilities are documented as adjacent platform modules where they affect deployment, data, or shared infrastructure; they are not assumed to be Cashflow business requirements.

## 2. Architecture & Tech Stack

### 2.1 Frontend

- **Language:** JavaScript/JSX, with TypeScript service files.
- **Framework:** React 19.
- **Build tool:** Vite 8.
- **Routing:** React Router.
- **Styling:** CSS plus Tailwind CSS v4 utility classes through `@tailwindcss/vite`; shared styles in `src/index.css` and `src/App.css`.
- **Icons:** `lucide-react`, with some inline Google SVG markup.
- **Charts:** `recharts` for dashboard trend and breakdown charts.
- **Spreadsheet support:** `xlsx` for browser-side spreadsheet workflows where used.
- **Authentication state:** `CashflowAuthContext` manages Supabase session, profile, invites, onboarding, and sign-out state.
- **API client:** `src/services/cashflowApi.ts` adds the `/api` base, bearer token, cache-control headers, and compatibility identity headers.
- **Tenant client:** `src/services/cashflowTenantApi.ts` wraps profile, company bootstrap, invite RPCs, and notification calls.

### 2.2 Frontend entry points and route groups

- `src/main.jsx` — React application bootstrap.
- `src/App.jsx` — route tree and authentication/provider composition.
- `src/components/cashflow/CashflowLayout.jsx` — protected application layout.
- `src/components/cashflow/CashflowSidebar.jsx` — Cashflow navigation.
- `src/components/CashflowProtectedRoute.jsx` — session, profile, company, and role guards.
- `src/context/CashflowAuthContext.jsx` — authentication and tenant profile lifecycle.

Important route groups include:

| Area | Routes |
|---|---|
| Login/reset | `/login`, `/cashflow/login`, `/cashflow/expense/login`, `/reset-password` |
| Onboarding | `/onboarding`, `/cashflow/expense/onboarding`, `/company/profile`, `/cashflow/expense/company-profile` |
| Dashboard | `/dashboard`, `/cashflow/dashboard` |
| AP | `/ap`, `/cashflow/ap` |
| AR | `/ar`, `/cashflow/ar` |
| Petty cash | `/petty-cash`, `/cashflow/pettycash` |
| Reconciliation | `/reconcile`, `/cashflow/reconcile` |
| Expenses | `/expenses`, `/cashflow/expense`, `/expenses/submit`, `/expenses/:id`, `/expenses/admin` |
| Invites | `/invite/accept`, `/cashflow/expense/accept-invite`, `/expenses/admin/invites`, `/cashflow/invites` |

### 2.3 Backend

- **Runtime:** Python Azure Functions using the classic per-function `function.json` model.
- **Primary API:** `api/`.
- **Dependencies:** Azure Functions, Supabase, pandas, openpyxl, PyMuPDF, pypdf, Azure Document Intelligence SDK, pydantic, OpenAI/Google/Qdrant/Langfuse integrations used by adjacent platform modules, and Azure storage/email libraries.
- **API route prefix:** `api/host.json` sets the HTTP route prefix to `/api`.
- **Timeout:** the primary Functions host is configured for a five-minute function timeout.
- **Shared backend:** authentication, database client creation, API contracts, tenant context/policy, audit, security, persistence, orchestration, retrieval, and document interfaces live under `api/shared/`.

### 2.4 Communications service

`comms-api/` is independently deployable and has its own host configuration, requirements, CORS/JSON helpers, and email client. Functions include:

- `tenant-invite-notify`
- `career-notify`
- `contact`

The Cashflow API calls the invite notification endpoint after creating an invitation through Supabase.

### 2.5 Database and infrastructure

- **System of record:** Supabase PostgreSQL and Supabase Auth.
- **Authorization:** bearer-token validation, profile/company resolution, membership functions, and PostgreSQL Row Level Security policies.
- **Schema:** SQL migrations under `api/shared/security/`, including base Cashflow tables, audit structures, membership hardening, quarantine/preflight, enforcement, and invite lifecycle functions.
- **Static hosting:** Azure Static Web Apps workflow under `.github/workflows/` builds/deploys the Vite application from the repository root.
- **Document processing:** local deterministic parsers for CSV/XLSX/PDF text, with Azure Document Intelligence fallback for scanned PDFs and image files.
- **External storage/AI:** adjacent platform code supports Azure Blob, queues, LLMs, vector retrieval, and Langfuse; these are not required for deterministic Cashflow CRUD but are part of the repository deployment surface.

## 3. Core Features & System Requirements

### 3.1 Authentication, onboarding, and tenant access

#### Implemented behavior

- Email/password sign-in.
- Password reset and password update flow.
- Email-link/OTP sign-in.
- Google OAuth sign-in.
- Session restoration with `supabase.auth.getSession()` and auth-state listeners.
- Profile retrieval through the `get_my_profile` Supabase RPC.
- First-time company creation through `bootstrap_company_owner`.
- Demo login using configurable Vite demo credentials, with optional demo-owner bootstrap.
- Profile cache clearing during sign-in changes and sign-out to avoid retaining a previous tenant.
- Protected routes that require a session and a valid Cashflow profile.
- Company-profile/onboarding redirection when a signed-in user has no company.

#### Roles and permissions

The shared policy defines four Cashflow roles:

- `owner`
- `admin`
- `finance`
- `employee`

Owners, admins, and finance users are approvers and can manage invitations. Employee users can use Cashflow when associated with a company but do not receive approval/invite permissions by default. Payment creation is restricted to approver roles in the shared policy.

#### Requirements

- Every protected financial request must resolve the authenticated tenant server-side.
- Client-provided company identifiers must never override the verified tenant.
- An authenticated user without a company must be directed to onboarding rather than being shown company data.
- A profile failure must fail closed and show a recoverable error state rather than rendering tenant-sensitive pages.

### 3.2 Cashflow dashboard

#### Implemented behavior

The dashboard frontend requests `/cashflow/dashboard`, supports period controls including one day, seven days, thirty days, current month, and custom dates, and renders:

- Cash received/inflow summary.
- Cash payable/outflow summary.
- Net cashflow.
- Outstanding/pending invoice and bill information.
- Petty-cash impact.
- Trend charts using Recharts.
- Breakdown charts for customers, vendors, and petty cash.
- Loading, empty, error, and refresh states.

The backend dashboard repository reads tenant-filtered transactions, petty cash, pending invoices, payable bills, and MSME-related bill candidates. Dashboard calculations are derived from the date window supplied by the frontend.

#### Requirements

- Dashboard figures must be company-scoped.
- Date-window filtering must apply consistently to all source datasets.
- The UI must remain usable when a source table is empty or unavailable during first-time setup.
- Financial amounts should use tabular numerals and INR-style formatting as currently presented by the UI.

### 3.3 Accounts payable

#### Implemented behavior

Frontend: `src/components/cashflow/AccountsPayable.jsx`. Backend: `api/cashflow_ap/` and `api/cashflow/ap/` repository code.

Capabilities include:

- List bills with vendor information.
- Upload invoice documents for OCR.
- Accept PDF and image formats in the frontend OCR flow.
- Extract bill number, GSTIN, amount, line-item, and vendor-related fields where OCR is available.
- Save a bill to the tenant company.
- Approve pending bills for authorized roles.
- Export displayed AP rows as CSV.
- Display empty/failure states when tables or OCR services are unavailable.

The backend stores bill/vendor relationships in `cashflow_bills` and `cashflow_entities`. The repository explicitly scopes vendor lookup and creation by company and entity type.

#### Amount requirements

The intended relationship is:

```text
gross amount = net amount + GST
net amount = gross amount - GST
```

The current frontend calculates/display fields interactively, while the backend accepts amount fields. Server-side validation should reject contradictory values before persistence.

### 3.4 Accounts receivable

#### Implemented behavior

Frontend: `src/components/cashflow/AccountsReceivable.jsx`. Backend: `api/cashflow_ar/` and `api/cashflow/ar/` repository code.

Capabilities include:

- List customer invoices.
- Create invoices with customer, GST, date, number, IRN, pro-forma, notes, and item/service information.
- Render/download an HTML invoice.
- Export invoice rows as CSV.
- Record collections through Cashflow transactions.
- Approve pending invoices for authorized roles.
- Resolve or create customers tenant-safely in `cashflow_entities`.

Invoices are stored in `cashflow_invoices`, with customer relationships to `cashflow_entities`. Invoice amounts are treated as gross values during bank matching unless a future contract changes that behavior.

### 3.5 Payments and transaction records

The payments module uses `cashflow_transactions` and supports listing tenant transactions, resolving a parent bill or invoice, validating the payment amount/date, and creating a transaction. Validation currently prevents:

- Payments against missing parent documents.
- Payments against cancelled documents.
- Payments larger than the parent document amount.
- Invalid transaction dates.

The shared repository attaches `company_id` and `created_by` server-side. Partial-payment allocation and cumulative settlement tracking are not fully represented in the current repository contract and are future scope.

### 3.6 Petty cash

Frontend: `src/components/cashflow/PettyCash.jsx`. Backend: `api/cashflow_pettycash/` and `api/cashflow/pettycash/`.

Capabilities include:

- List petty-cash entries.
- Create inflow/outflow entries with date, amount, type, description, and category.
- Set entries to pending on creation.
- Approve entries for authorized users.
- Export ledger data as CSV.
- Include petty cash in dashboard and bank-reconciliation source data.

The current schema uses `cashflow_petty_cash` with `cash_in` and `cash_out` fields. The backend deliberately uses existing schema fields rather than introducing a separate petty-cash schema.

### 3.7 Bank statement parsing and reconciliation

Frontend: `src/components/cashflow/BankStatementReconcile.jsx`. Backend: `api/cashflow_reconcile/`.

#### Supported input

- CSV
- XLSX/XLS
- PDF
- JPEG/JPG
- PNG
- TIFF

#### Processing

1. Validate file name/extension and upload size.
2. Decode base64 content.
3. Parse CSV and Excel deterministically using header detection and normalized column names.
4. Extract native PDF text where possible.
5. Use Azure Document Intelligence `prebuilt-layout` for scanned PDFs/images or PDFs without usable text.
6. Normalize rows into transaction records.
7. Parse dates, INR/decimal values, debit/credit direction, references, narration, and balances.
8. Return row validation issues and non-blocking balance warnings.
9. Optionally query AP, AR, and petty-cash records for the authenticated company.
10. Match bank records to platform records using date tolerance, amount tolerance, references, and normalized party/description values.
11. Persist the run and reconciliation rows.

#### Reconciliation statuses

- `matched`
- `amount_mismatch`
- `missing_in_bank_statement`
- `unexpected_in_bank_statement`

Bank-only mode is an import/review workflow. It does not compare against an empty platform dataset and therefore does not create false unexpected mismatches.

#### Persistence

`cashflow_bank_reconcile_runs` stores company, date range, source-file metadata, summary, creator, and timestamp. `cashflow_bank_reconcile_rows` stores source side, voucher data, amount, status, notes, and raw data. Export and recent-run endpoints apply company filters.

### 3.8 Workspace invitations and membership

#### Implemented behavior

- Authorized users create company invites through Supabase RPC.
- Invite role is employee/admin as exposed by the current client contract.
- The API calls the communications function to send the invite email.
- The email includes a direct acceptance URL.
- Invitees can create an account, sign in, or use Google.
- Invite acceptance checks authenticated email against the invited email.
- Invite acceptance is one-time and uses row locking in the hardening migration.
- Expired invites are marked expired when listed or accepted.
- Existing users are not silently moved between companies.
- The invited role is authoritative when profile/membership state is updated.
- Authorized administrators can revoke pending invites.

### 3.9 Existing employee-expense module

The repository also contains expense submission, detail, status history, attachments, administrative queue, and invite pages. These use Supabase services and SQL audit/history structures. They share the Cashflow auth/layout surface and are routed under both `/expenses` and selected `/cashflow` paths.

This module is treated as an adjacent capability because the repository does not establish that expense management is a new Cashflow-specific product requirement. Its presence does, however, impose compatibility requirements on shared authentication, tenant policy, navigation, and database security.

## 4. Data Models & Flow

### 4.1 Identity and tenant model

The primary identity flow is:

```text
Supabase Auth session
  → bearer access token
  → server identity validation
  → profile/membership resolution
  → TenantContext(user_id, company_id, role)
  → tenant-scoped query/mutation
```

The backend `TenantContext` abstraction contains `user_id`, `company_id`, `role`, and optional email/name. Feature repositories depend on this context instead of directly accepting a client-supplied company ID.

### 4.2 Core entities

The SQL and repository code evidence the following core structures:

- `profiles` — authenticated user profile, role, company association, and setup state.
- `company_memberships` — user/company membership, role, status, and timestamps.
- `company_invites` — invite email, role, token, status, expiry, acceptance, and revocation metadata.
- `cashflow_entities` — vendors and customers, company-scoped by `entity_type`.
- `cashflow_bills` — AP bill records, amounts, GST, dates, status, and vendor relationship.
- `cashflow_invoices` — AR invoice records, amounts, GST, dates, status, pro-forma state, and customer relationship.
- `cashflow_transactions` — payments/collections and transaction records linked to bills/invoices where applicable.
- `cashflow_petty_cash` — petty-cash inflow/outflow records and approval state.
- `cashflow_bank_reconcile_runs` — reconciliation run metadata and aggregate summary.
- `cashflow_bank_reconcile_rows` — persisted bank/platform comparison rows and raw data.
- `cashflow_audit` — audit records for financial/security operations where enabled.
- `expenses`, `expense_status_history`, and `expense_attachments` — adjacent employee-expense data.

### 4.3 Normalized bank transaction shape

The reconciliation parser produces records shaped like:

```json
{
  "transaction_date": "YYYY-MM-DD",
  "value_date": "YYYY-MM-DD",
  "description": "Transaction narration",
  "reference": "Bank reference",
  "debit": 0,
  "credit": 0,
  "amount": 0,
  "direction": "debit|credit|unknown",
  "balance": 0,
  "source_row_number": 1,
  "extraction_method": "csv|xlsx|pdf_text|azure_document_intelligence",
  "confidence": 1.0,
  "raw_data": {}
}
```

Dates and money values are normalized before matching. Indian number/date formats and common bank column aliases are supported by the parser.

### 4.4 Reconciliation flow

```text
Browser file picker
  → base64 request to /api/reconcile/bank/analyze
  → extension/size/base64 validation
  → local parser or Azure OCR
  → normalized bank rows
  → optional tenant AP/AR/petty-cash reads
  → candidate scoring and status assignment
  → reconciliation run + rows persisted to Supabase
  → summary/sample mismatches returned to React
  → CSV export or recent-run review
```

There is no streaming or realtime reconciliation pipeline in the current code. Processing is synchronous inside the HTTP-triggered function. The frontend uses request cancellation/identity guards in several modules to avoid stale responses being applied after a tenant/session switch.

### 4.5 Audit and quarantine flow

Security migrations use a fail-closed data repair process. The phase-7 preflight migration copies unsafe/orphaned row evidence into `cashflow_phase7_quarantine`; enforcement is intended only after operators repair and mark unresolved rows. This prevents the migration from guessing ownership of legacy data.

## 5. System Workflows / API Contracts

### 5.1 Response conventions

Cashflow functions generally return:

```json
{ "ok": true, "data": {} }
```

or an error such as:

```json
{ "ok": false, "error": "Description" }
```

The reconciliation function also uses a compatibility envelope with `success` and `error` fields for its current frontend contract. The communications service uses:

```json
{ "ok": true, "data": {}, "error": null, "trace_id": "..." }
```

### 5.2 Primary Cashflow endpoints

The Azure function route prefix is `/api`.

#### Dashboard

```http
GET /api/cashflow/dashboard
```

Returns tenant-scoped summary/trend data for the requested date window.

#### Accounts payable

```http
GET  /api/cashflow/ap/list
POST /api/cashflow/ap/ocr
POST /api/cashflow/ap/save
POST /api/cashflow/ap/approve
```

#### Accounts receivable

```http
GET  /api/cashflow/ar/list
POST /api/cashflow/ar/create
POST /api/cashflow/ar/collect
POST /api/cashflow/ar/approve
```

#### Payments

```http
GET  /api/cashflow/payments
POST /api/cashflow/payments
```

The exact accepted payload depends on resource type and current function implementation; parent resources are resolved within the authenticated tenant.

#### Petty cash

```http
GET  /api/cashflow/pettycash
POST /api/cashflow/pettycash
POST /api/cashflow/pettycash/approve
```

#### Reconciliation

```http
POST /api/reconcile/bank/analyze
GET  /api/reconcile/bank/export?run_id=...&kind=mismatch
GET  /api/reconcile/bank/export?run_id=...&kind=corrected
GET  /api/reconcile/bank/recent?limit=5
```

Analyze request:

```json
{
  "start_date": "YYYY-MM-DD",
  "end_date": "YYYY-MM-DD",
  "file_name": "statement.csv",
  "file_content_base64": "...",
  "compare_with_platform": true
}
```

The response includes a run ID, summary, sample mismatches, uploaded normalized rows, column warnings, row issue count, and comparison mode.

#### Invite notification proxy

```http
POST /api/cashflow/invites/notify
```

This endpoint validates/forwards invitation notification data to the communications service. Invite creation and acceptance themselves use Supabase RPCs:

- `create_company_invite`
- `list_company_invites`
- `accept_company_invite`
- `revoke_company_invite`
- `get_my_profile`
- `bootstrap_company_owner`

### 5.3 Authentication workflow

```text
Login page
  → Supabase email/password, email link, or Google OAuth
  → auth state event/session restoration
  → get_my_profile RPC
  → company/setup decision
  → dashboard, onboarding, company profile, or invite acceptance
```

OAuth and invite URLs retain token/email/role context through the redirect path. Invite acceptance must still rely on server-side email verification rather than query-string trust.

### 5.4 AP/AR approval workflow

```text
User creates bill/invoice
  → record starts pending
  → owner/admin/finance reviews
  → approve endpoint validates role and current state
  → record transitions to approved
  → dashboard and reconciliation include approved source data
```

The current code prevents approval of records already in incompatible states. Full approval history and configurable multi-step approvals are future scope.

### 5.5 Invite workflow

```text
Admin creates invite
  → company_invites row created through RPC
  → notification endpoint called
  → email sent by comms-api
  → invitee opens token URL
  → create account/sign in/Google
  → server verifies invited email, expiry, status, and workspace conflict
  → membership/profile updated atomically
  → invite marked accepted
```

If email delivery fails synchronously, the current client attempts best-effort revocation. Ambiguous delivery timeout handling should remain fail-safe and must not expose or silently transfer membership.

## 6. Dependencies & Integrations

### 6.1 Supabase

Used for:

- Email/password, email-link, and Google authentication.
- Session and JWT issuance.
- PostgreSQL tables and RPC functions.
- Tenant profiles and company memberships.
- Invite lifecycle functions.
- RLS enforcement.
- Audit and reconciliation persistence.

### 6.2 Azure Functions

Used to host the primary API and communications API. Function configuration controls route prefix, CORS, timeout, and runtime extension bundles.

### 6.3 Azure Document Intelligence

Used as OCR/table-layout fallback for scanned bank statements and AP invoice documents. Settings support both repository-specific and conventional endpoint/key variable names. OCR-derived values are inherently lower trust than deterministic CSV/XLSX parsing and require review UX.

### 6.4 Email delivery

The communications service uses Azure Communication Email through `comms-api/shared/email_client.py`. Invite notifications are separated from the main API deployment.

### 6.5 Browser and data libraries

- `recharts` — dashboard visualizations.
- `xlsx` — spreadsheet parsing/export support.
- `pandas`/`openpyxl` — server-side spreadsheet normalization.
- `PyMuPDF`/`pypdf` — native PDF extraction.
- `lucide-react` — UI icons.

### 6.6 Adjacent platform integrations

The repository includes optional/adjacent infrastructure for:

- Azure Blob Storage and queues.
- OpenAI and Google generative AI clients.
- Qdrant vector retrieval.
- Langfuse tracing.
- Web crawling, knowledge ingestion, resume parsing/tailoring, ATS scoring, and careers notifications.

These integrations should not be made mandatory for basic Cashflow CRUD or deterministic bank import.

## 7. Security & Performance Considerations

### 7.1 Security controls present

- Supabase bearer-token authentication for tenant APIs.
- Shared `require_cashflow_tenant` authorization boundary.
- Tenant context abstraction and tenant-filtered repository queries.
- Role policy for Cashflow usage, approval, invites, and payments.
- RLS/security SQL migrations.
- Company ownership checks on reconciliation run/export access.
- Invite expiry, one-time acceptance, row locking, email matching, and workspace-conflict checks.
- Profile cache clearing during identity changes.
- Upload extension and size validation.
- Base64 decoding validation.
- Avoidance of access-token/secret logging in the inspected Cashflow clients.
- Communications CORS allow-list and trace IDs.
- Quarantine-before-enforcement migration strategy for legacy ownership data.

### 7.2 Security risks and gaps

1. **Local settings:** `api/local.settings.json` and communications local settings must never be committed with real credentials. Secrets should be rotated if exposed and supplied through deployment configuration.
2. **Legacy identity headers:** compatibility `x-user-id`/role/company headers remain in the client for local/dev behavior. Authenticated production requests must continue to ignore client-supplied tenant claims.
3. **AP amount integrity:** enforce gross/net/GST consistency server-side.
4. **OCR trust:** require confidence thresholds and human confirmation for financial values extracted from scans.
5. **Invite delivery ambiguity:** a timeout does not prove delivery failure. Delivery status should be tracked asynchronously before automatically revoking or retrying.
6. **OAuth invite matching:** server-side verification is mandatory; client query parameters are informational only.
7. **Raw-data retention:** reconciliation rows may retain narration, references, account identifiers, or personal data. Define retention, masking, and deletion policies.
8. **Export sensitivity:** CSV exports contain financial data and must remain tenant-scoped and access-controlled.
9. **Error detail:** production responses should not expose database internals or provider secrets; logs should retain traceable diagnostics without credentials.

### 7.3 Performance constraints

- Reconciliation is synchronous within an HTTP function and may approach the five-minute host timeout.
- OCR introduces external latency and cost.
- Large spreadsheets are loaded into memory through pandas/openpyxl.
- Reconciliation matching is Python-side and can become expensive as bank/platform row counts grow.
- Dashboard aggregation currently performs multiple source queries per request.
- Frontend bundle size exceeds the common 500 kB warning threshold; code splitting is advisable.
- Database indexes should cover `company_id`, date columns, invoice/bill numbers, reconciliation run IDs, and relationship keys.
- Persisted raw reconciliation data can increase storage and query volume.

### 7.4 Reliability requirements

- API operations should be idempotent where retries are likely, especially invite notifications and reconciliation submission.
- Stale frontend requests must not overwrite state after identity/company changes.
- Missing/unmigrated tables should produce recoverable setup errors rather than data leakage.
- OCR/parser warnings should be non-blocking when rows remain reviewable.

### 7.5 Recommended scaling path

For large statements:

```text
Upload
  → durable job record
  → queue/background parser
  → persisted progress and diagnostics
  → reconciliation result
  → frontend polling or realtime updates
```

## 8. Future Scope

### 8.1 Product enhancements

- Partial-payment allocation and cumulative settlement tracking.
- Credit notes and debit notes.
- Vendor/customer statement matching.
- Bank-fee categorization and duplicate-charge detection.
- Cash-position forecasting.
- GST reporting and reconciliation.
- Approval workflows with configurable steps and audit history.
- Attachments and audit-ready source documents.
- Multi-bank and multi-account support.
- Manual reconciliation review/correction/posting queue.
- Accounting-system export formats.
- Account-level opening/closing balance support.

### 8.2 Reconciliation improvements

- More bank-specific layouts and header detection.
- Better native PDF table extraction.
- OCR confidence thresholds and field-level review.
- Page/table coordinates for audit evidence.
- Duplicate transaction detection.
- Candidate-match metadata for date differences without expanding the current status contract.
- Configurable amount/date matching policies.
- Asynchronous processing and progress status.
- Downloadable source-document audit records.

### 8.3 Backend and data improvements

- Strengthen AP amount validation and normalize contradictory values.
- Add database constraints/checks for financial invariants where compatible with legacy data.
- Introduce migration version tracking and operator runbooks.
- Finish phase-7 ownership quarantine repair and enforcement operational process.
- Add indexes based on production query plans.
- Replace broad raw-data retention with documented masking/retention rules.
- Consolidate repeated response envelopes while retaining frontend compatibility.

### 8.4 Testing and quality

Add automated tests for:

- CSV parsing and bank-column aliases.
- Excel header detection.
- Native PDF and OCR normalization.
- Indian number/date formats.
- GST calculations and AP amount invariants.
- Reconciliation matching tolerance and duplicate handling.
- Running-balance validation.
- Tenant isolation and role permissions.
- Invite expiry, email mismatch, concurrent acceptance, and revocation.
- API contract compatibility between frontend and Azure Functions.

Recommended CI checks:

- Frontend build.
- Frontend lint.
- Python compilation and tests.
- SQL migration validation.
- Secret scanning.
- Dependency and vulnerability scanning.

### 8.5 Technical debt observed in the repository

- The reconciliation function is concentrated in one large module and should be split into parser, normalizer, matcher, persistence, and HTTP layers when compatibility permits.
- Frontend lint currently reports React hook/state issues and unused variables across Cashflow and legacy expense pages.
- The frontend production bundle emits a chunk-size warning.
- Tracked/generated Python cache artifacts should be removed from version control and kept ignored.
- Repeated Google icon markup should become a shared component.
- Communications delivery status is not durable or asynchronous.
- Some adjacent platform modules have optional providers and fallback paths that require clearer deployment documentation.

### 8.6 Architectural assumptions

1. Supabase remains the authentication, tenancy, and financial system of record.
2. The first reconciliation release compares only AP, AR, and petty cash.
3. Bank-only parsing is an import/review workflow, not mismatch reconciliation.
4. Azure Document Intelligence is used only when deterministic local parsing is unsuitable.
5. Existing frontend response shapes and route aliases are compatibility contracts.
6. Company isolation is mandatory for every financial, invite, expense, and export operation.
7. The adjacent careers/resume platform remains separately scoped even though it shares backend dependencies and repository infrastructure.
