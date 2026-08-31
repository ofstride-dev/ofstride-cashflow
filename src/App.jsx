import { Navigate, Route, Routes } from 'react-router-dom'
import { CashflowAuthProvider } from './context/CashflowAuthContext'
import CashflowProtectedRoute from './components/CashflowProtectedRoute'
import CashflowLayout from './components/cashflow/CashflowLayout'
import CashflowDashboard from './components/cashflow/CashflowDashboard'
import CashflowLogin from './pages/cashflow/CashflowLogin'
import CashflowOnboarding from './pages/cashflow/CashflowOnboarding'
import CashflowCompanyProfile from './pages/cashflow/CashflowCompanyProfile'
import CashflowResetPassword from './pages/cashflow/CashflowResetPassword'

import AccountsPayable from './components/cashflow/AccountsPayable'
import AccountsReceivable from './components/cashflow/AccountsReceivable'
import BankStatementReconcile from './components/cashflow/BankStatementReconcile'

import MyExpenses from './pages/expenses/MyExpenses'
import SubmitExpense from './pages/expenses/SubmitExpense'
import ExpenseDetail from './pages/expenses/ExpenseDetail'
import AdminExpenseQueue from './pages/expenses/AdminExpenseQueue'
import AdminInvites from './pages/expenses/AdminInvites'
import AcceptInvite from './pages/expenses/AcceptInvite'

function App() {
  return (
    <CashflowAuthProvider>
      <Routes>
        {/* Auth / public routes */}
        <Route path="/login" element={<CashflowLogin />} />
        <Route path="/cashflow/login" element={<CashflowLogin />} />
        <Route path="/cashflow/expense/login" element={<CashflowLogin />} />
        <Route path="/reset-password" element={<CashflowResetPassword />} />
        <Route path="/invite/accept" element={<AcceptInvite />} />

        {/* Setup and invite routes must be reachable before a company exists. */}
        <Route
          element={
            <CashflowProtectedRoute allowWithoutCompany>
              <CashflowLayout />
            </CashflowProtectedRoute>
          }
        >
          <Route path="/onboarding" element={<CashflowOnboarding />} />
          <Route path="/cashflow/expense/onboarding" element={<CashflowOnboarding />} />
          <Route path="/company/profile" element={<CashflowCompanyProfile />} />
          <Route path="/cashflow/expense/company-profile" element={<CashflowCompanyProfile />} />
        </Route>

        {/* Invite acceptance can be completed before the user has a company. */}
        <Route path="/cashflow/expense/accept-invite" element={<AcceptInvite />} />

        {/* Protected app routes */}
        <Route
          element={
            <CashflowProtectedRoute>
              <CashflowLayout />
            </CashflowProtectedRoute>
          }
        >
          {/* Dashboard */}
          <Route path="/dashboard" element={<CashflowDashboard />} />
          <Route path="/cashflow/dashboard" element={<CashflowDashboard />} />

          {/* Cashflow modules */}
          <Route path="/ap" element={<AccountsPayable />} />
          <Route path="/cashflow/ap" element={<AccountsPayable />} />
          <Route path="/ar" element={<AccountsReceivable />} />
          <Route path="/cashflow/ar" element={<AccountsReceivable />} />
          {/* Petty Cash was retired; preserve old bookmarks by routing claims to the portal. */}
          <Route path="/petty-cash" element={<Navigate to="/cashflow/expense" replace />} />
          <Route path="/cashflow/pettycash" element={<Navigate to="/cashflow/expense" replace />} />
          <Route path="/reconcile" element={<BankStatementReconcile />} />
          <Route path="/cashflow/reconcile" element={<BankStatementReconcile />} />

          {/* Expenses */}
          <Route path="/expenses" element={<MyExpenses />} />
          <Route path="/cashflow/expense" element={<MyExpenses />} />
          <Route path="/expenses/new" element={<SubmitExpense />} />
          <Route path="/cashflow/expense/new" element={<SubmitExpense />} />
          <Route path="/expenses/submit" element={<SubmitExpense />} />
          <Route path="/expenses/:id" element={<ExpenseDetail />} />
          <Route path="/cashflow/expense/:id" element={<ExpenseDetail />} />
          <Route path="/expenses/admin" element={<AdminExpenseQueue />} />
          <Route path="/cashflow/expense/admin" element={<AdminExpenseQueue />} />
          <Route path="/expenses/admin/invites" element={<AdminInvites />} />
          <Route path="/cashflow/invites" element={<AdminInvites />} />
          <Route path="/cashflow/expenses/admin/invites" element={<AdminInvites />} />

        </Route>

        {/* Redirects */}
        <Route path="/" element={<Navigate to="/dashboard" replace />} />
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Routes>
    </CashflowAuthProvider>
  )
}

export default App