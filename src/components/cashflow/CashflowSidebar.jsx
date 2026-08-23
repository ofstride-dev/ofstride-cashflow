import { useState } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { 
  LayoutDashboard, 
  LogOut, 
  UserPlus, 
  X,
  ChevronLeft,
  ChevronRight
} from 'lucide-react';
import { useCashflowAuth } from '../../context/CashflowAuthContext';

const navItems = [
  { path: '/cashflow/dashboard', label: 'Dashboard', icon: LayoutDashboard },
];

export default function CashflowSidebar({ mobileOpen, onClose }) {
  const { session, profile, isAdmin, signOut } = useCashflowAuth();
  const [collapsed, setCollapsed] = useState(false);
  const location = useLocation();

  const sidebarWidth = collapsed ? 'w-20' : 'w-64';
  const showText = !collapsed;

  const SidebarContent = () => (
    <div className={`flex flex-col h-full bg-of-sidebar text-of-sidebar-text transition-all duration-300 ${sidebarWidth}`}>
      <div className="flex items-center gap-3 px-4 h-16 border-b border-of-sidebar-border flex-shrink-0">
        <div className="w-9 h-9 rounded-lg bg-of-primary flex items-center justify-center flex-shrink-0 shadow-of-glow">
          <span className="text-white font-bold text-sm">O</span>
        </div>
        {showText && (
          <div className="flex flex-col overflow-hidden">
            <span className="text-of-sidebar-active font-semibold text-sm leading-tight truncate">Ofstride</span>
            <span className="text-[11px] text-of-sidebar-text/60">Cashflow</span>
          </div>
        )}
        {showText ? (
          <button 
            onClick={() => setCollapsed(true)}
            className="ml-auto p-1.5 rounded-lg hover:bg-of-sidebar-hover text-of-sidebar-text/40 hover:text-of-sidebar-active transition-all"
          >
            <ChevronLeft size={16} />
          </button>
        ) : (
          <button 
            onClick={() => setCollapsed(false)}
            className="mx-auto p-1.5 rounded-lg hover:bg-of-sidebar-hover text-of-sidebar-text/40 hover:text-of-sidebar-active transition-all"
          >
            <ChevronRight size={16} />
          </button>
        )}
      </div>

      <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive = location.pathname === item.path;
          return (
            <NavLink
              key={item.path}
              to={item.path}
              onClick={onClose}
              className={`of-sidebar-link ${isActive ? 'active' : ''} ${collapsed ? 'justify-center px-2' : ''}`}
              title={collapsed ? item.label : ''}
            >
              <Icon size={20} strokeWidth={isActive ? 2.5 : 2} />
              {showText && <span className="truncate">{item.label}</span>}
            </NavLink>
          );
        })}
      </nav>

      <div className="p-3 border-t border-of-sidebar-border space-y-2 flex-shrink-0">
        {isAdmin && (
          <button 
            className={`of-btn of-btn-secondary w-full text-xs !py-2 border-of-sidebar-border bg-of-sidebar-hover hover:bg-of-sidebar-hover/80 hover:border-of-primary hover:text-of-primary transition-all ${collapsed ? '!px-2 justify-center' : ''}`}
          >
            <UserPlus size={collapsed ? 16 : 14} />
            {showText && 'Invite Admin'}
          </button>
        )}

        <div className={`flex items-center gap-3 px-3 py-2.5 rounded-xl bg-of-sidebar-hover/50 border border-of-sidebar-border/50 ${collapsed ? 'justify-center' : ''}`}>
          <div className="w-8 h-8 rounded-full bg-of-primary/20 flex items-center justify-center flex-shrink-0">
            <span className="text-of-primary font-bold text-xs">
              {(profile?.full_name || session?.user?.email || 'U').charAt(0).toUpperCase()}
            </span>
          </div>
          {showText && (
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-of-sidebar-active truncate">
                {profile?.company_name || 'Workspace'}
              </p>
              <p className="text-[11px] text-of-sidebar-text/60 truncate">
                {session?.user?.email}
              </p>
            </div>
          )}
        </div>

        <button 
          onClick={signOut}
          className={`of-btn of-btn-secondary w-full text-of-sidebar-text hover:text-of-danger hover:border-of-danger/30 hover:bg-of-danger/10 transition-all ${collapsed ? '!p-2 justify-center' : '!py-2 text-xs'}`}
        >
          <LogOut size={collapsed ? 16 : 14} />
          {showText && 'Sign Out'}
        </button>
      </div>
    </div>
  );

  return (
    <>
      <aside className="hidden lg:block fixed left-0 top-0 h-screen z-40">
        <SidebarContent />
      </aside>

      {mobileOpen && (
        <div className="lg:hidden fixed inset-0 z-50 flex">
          <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={onClose} />
          <div className="relative w-64 h-full animate-slide-in-left">
            <button 
              onClick={onClose}
              className="absolute top-4 right-4 p-2 rounded-lg bg-of-sidebar-hover text-of-sidebar-active z-10"
            >
              <X size={20} />
            </button>
            <SidebarContent />
          </div>
        </div>
      )}
    </>
  );
}
