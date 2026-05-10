import { Link, useLocation } from "react-router-dom";
import { LayoutDashboard, GitBranch, Settings, BarChart3, LogOut, Terminal } from "lucide-react";
import { useAuthStore } from "../../store/index";

export default function Layout({ children }: { children: React.ReactNode }) {
  const location = useLocation();
  const logout = useAuthStore((state) => state.logout);

  const navItems = [
    { path: "/dashboard", icon: LayoutDashboard, label: "Dashboard" },
    { path: "/repositories", icon: GitBranch, label: "Repositories" },
    { path: "/analytics", icon: BarChart3, label: "Analytics" },
    { path: "/settings", icon: Settings, label: "Settings" },
  ];

  const isActive = (path: string) => {
    if (path === "/dashboard" && location.pathname === "/") return true;
    return location.pathname.startsWith(path);
  };

  return (
    <div className="flex min-h-screen bg-bg-primary font-sans text-text-primary">
      {/* Sidebar */}
      <aside className="w-72 fixed h-full glass border-r border-border hidden md:flex flex-col z-50">
        <div className="p-8 flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-accent to-accent-dark flex items-center justify-center shadow-accent">
            <Terminal className="text-white w-6 h-6" />
          </div>
          <div>
            <h1 className="text-xl font-bold tracking-tight text-white leading-none">DevMind</h1>
            <span className="text-[10px] uppercase tracking-[0.2em] text-accent font-bold">AI Agent</span>
          </div>
        </div>

        <nav className="flex-1 px-4 space-y-2 py-4">
          <p className="px-4 text-[10px] font-bold text-text-muted uppercase tracking-[0.2em] mb-4">Main Menu</p>
          {navItems.map((item) => (
            <Link
              key={item.path}
              to={item.path}
              className={`flex items-center gap-3 px-4 py-3 rounded-xl transition-all group ${
                isActive(item.path)
                  ? "bg-accent/10 text-accent border border-accent/20 shadow-sm shadow-accent/5"
                  : "text-text-secondary hover:bg-white/5 hover:text-text-primary"
              }`}
            >
              <item.icon className={`w-5 h-5 transition-transform group-hover:scale-110 ${
                isActive(item.path) ? "text-accent" : "text-text-muted group-hover:text-accent"
              }`} />
              <span className="font-semibold">{item.label}</span>
              {isActive(item.path) && (
                <div className="ml-auto w-1.5 h-1.5 rounded-full bg-accent shadow-[0_0_8px_var(--accent)]" />
              )}
            </Link>
          ))}
        </nav>

        <div className="p-4 mt-auto">
          <div className="glass-card p-4 mb-4 bg-bg-tertiary/30">
            <p className="text-xs font-bold text-accent mb-1">PRO PLAN</p>
            <p className="text-[10px] text-text-muted leading-relaxed">
              Unlimited AI reviews and priority scanning active.
            </p>
          </div>
          <button
            onClick={logout}
            className="flex items-center gap-3 px-4 py-3 text-text-secondary hover:bg-error/10 hover:text-error transition-all rounded-xl w-full group"
          >
            <LogOut className="w-5 h-5 group-hover:-translate-x-1 transition-transform" />
            <span className="font-semibold">Logout</span>
          </button>
        </div>
      </aside>

      {/* Main Content */}
      <main className="flex-1 md:ml-72 min-h-screen">
        <header className="h-20 border-b border-border flex items-center justify-end px-8 sticky top-0 bg-bg-primary/80 backdrop-blur-md z-40">
          <div className="flex items-center gap-4">
            <div className="text-right hidden sm:block">
              <p className="text-sm font-bold text-text-primary">Admin User</p>
              <p className="text-[10px] text-accent font-bold uppercase tracking-wider">Maintainer</p>
            </div>
            <div className="w-10 h-10 rounded-full bg-gradient-to-tr from-accent-dark to-accent border-2 border-border-bright p-0.5">
              <div className="w-full h-full rounded-full bg-bg-primary overflow-hidden">
                <img src="https://api.dicebear.com/7.x/avataaars/svg?seed=admin" alt="avatar" />
              </div>
            </div>
          </div>
        </header>

        <div className="p-8 max-w-7xl mx-auto">
          {children}
        </div>
      </main>
    </div>
  );
}
