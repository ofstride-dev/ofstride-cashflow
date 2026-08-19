import { Navigate, Route, Routes } from 'react-router-dom'
import { CashflowAuthProvider } from './context/CashflowAuthContext'
import CashflowProtectedRoute from './components/CashflowProtectedRoute'
import CashflowLayout from './components/cashflow/CashflowLayout'
import CashflowDashboard from './components/cashflow/CashflowDashboard'
import CashflowLogin from './pages/cashflow/CashflowLogin'

function App() {
  return (
    <CashflowAuthProvider>
      <Routes>
        <Route path="/login" element={<CashflowLogin />} />
        <Route path="/cashflow/login" element={<CashflowLogin />} />
        <Route
          element={
            <CashflowProtectedRoute>
              <CashflowLayout />
            </CashflowProtectedRoute>
          }
        >
          <Route path="/dashboard" element={<CashflowDashboard />} />
          <Route path="/cashflow/dashboard" element={<CashflowDashboard />} />
        </Route>
        <Route path="/" element={<Navigate to="/dashboard" replace />} />
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Routes>
    </CashflowAuthProvider>
  )
}

export default App
