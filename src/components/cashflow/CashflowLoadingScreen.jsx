import { BarChart3, Sparkles } from 'lucide-react';

export default function CashflowLoadingScreen({ message = 'Getting your dashboard ready…' }) {
  return (
    <div className="cashflow-loading-screen" role="status" aria-live="polite" aria-busy="true">
      <div className="cashflow-loading-orb" aria-hidden="true">
        <div className="cashflow-loading-ring" />
        <div className="cashflow-loading-icon"><BarChart3 className="h-6 w-6" /></div>
      </div>
      <p className="cashflow-loading-brand">OFSTRIDE <span>/</span> CASHFLOW</p>
      <h1>{message}</h1>
      <p className="cashflow-loading-caption">Securely loading your workspace data and financial insights</p>
      <div className="cashflow-loading-track" aria-hidden="true"><span /></div>
      <div className="cashflow-loading-footnote"><Sparkles className="h-3.5 w-3.5" /> Your workspace is almost ready</div>
    </div>
  );
}