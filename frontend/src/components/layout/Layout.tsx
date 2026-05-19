import { Link, useLocation } from "react-router-dom";
import { useAuthStore } from "../../store/index";
import { LayoutDashboard, GitBranch, Settings, BarChart3, LogOut, Terminal } from "lucide-react";
import { useEffect, useState } from "react";

interface UserProfile {
  id: number;
  email: string;
  github_login: string;
  avatar_url: string;
}

export default function Layout({ children }: { children: React.ReactNode }) {
  const location = useLocation();
  const logout = useAuthStore((state) => state.logout);
  const [user, setUser] = useState<UserProfile | null>(null);

  useEffect(() => {
    fetch("/api/v1/auth/me/")
      .then(res => {
        if (res.ok) return res.json();
        throw new Error();
      })
      .then((data: UserProfile) => setUser(data))
      .catch(() => {
        // not authenticated or error
      });
  }, []);

  const navItems = [
    { path: "/dashboard", icon: LayoutDashboard, label: "Dashboard" },
    { path: "/repositories", icon: GitBranch, label: "Repositories" },
    { path: "/analytics", icon: BarChart3, label: "Analytics" },
    { path: "/settings", icon: Settings, label: "Settings" },
  ];

  const isActive = (path: string) => {
    if (path === "/dashboard" && (location.pathname === "/" || location.pathname === "/dashboard")) return true;
    return location.pathname.startsWith(path);
  };

  const handleLogout = () => {
    logout();
    window.location.href = "/login";
  };

  return (
    <div className="flex min-h-screen" style={{ backgroundColor: "var(--bg-primary)", color: "var(--text-primary)" }}>
      <aside
        className="w-72 fixed h-full hidden md:flex flex-col z-50"
        style={{ backgroundColor: "rgba(20,20,24,0.7)", backdropFilter: "blur(12px)", borderRight: "1px solid var(--glass-border)" }}
      >
        <div className="p-8 flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl flex items-center justify-center shadow-accent" style={{ background: "linear-gradient(135deg, var(--accent) 0%, var(--accent-dark) 100%)" }}>
            <Terminal className="text-white w-6 h-6" />
          </div>
          <div>
            <h1 className="text-xl font-bold tracking-tight leading-none" style={{ color: "var(--text-primary)" }}>DevMind</h1>
            <span className="text-[10px] uppercase tracking-[0.2em] font-bold" style={{ color: "var(--accent)" }}>AI Agent</span>
          </div>
        </div>

        <nav className="flex-1 px-4 space-y-2 py-4">
          <p className="px-4 text-[10px] font-bold uppercase tracking-[0.2em] mb-4" style={{ color: "var(--text-muted)" }}>Main Menu</p>
          {navItems.map((item) => (
            <Link
              key={item.path}
              to={item.path}
              className="flex items-center gap-3 px-4 py-3 rounded-xl transition-all group"
              style={isActive(item.path)
                ? { backgroundColor: "rgba(139,92,246,0.1)", color: "var(--accent)", border: "1px solid rgba(139,92,246,0.2)", boxShadow: "0 0 8px rgba(139,92,246,0.05)" }
                : { color: "var(--text-secondary)" }
              }
            >
              <item.icon className={`w-5 h-5 transition-transform group-hover:scale-110 ${isActive(item.path) ? "" : "group-hover:text-accent"}`} style={isActive(item.path) ? { color: "var(--accent)" } : { color: "var(--text-muted)" }} />
              <span className="font-semibold">{item.label}</span>
              {isActive(item.path) && (
                <div className="ml-auto w-1.5 h-1.5 rounded-full" style={{ backgroundColor: "var(--accent)", boxShadow: "0 0 8px rgba(139,92,246,0.4)" }} />
              )}
            </Link>
          ))}
        </nav>

        <div className="p-4 mt-auto">
          <div className="glass-card p-4 mb-4" style={{ backgroundColor: "rgba(31,31,35,0.3)" }}>
            <p className="text-xs font-bold mb-1" style={{ color: "var(--accent)" }}>PRO PLAN</p>
            <p className="text-[10px] leading-relaxed" style={{ color: "var(--text-muted)" }}>
              Unlimited AI reviews and priority scanning active.
            </p>
          </div>
          <button
            onClick={handleLogout}
            className="flex items-center gap-3 px-4 py-3 rounded-xl w-full group"
            style={{ color: "var(--text-secondary)" }}
          >
            <LogOut className="w-5 h-5 group-hover:-translate-x-1 transition-transform" />
            <span className="font-semibold">Logout</span>
          </button>
        </div>
      </aside>

      <main className="flex-1 md:ml-72 min-h-screen">
        <header className="h-20 border-b flex items-center justify-end px-8 sticky top-0 z-40" style={{ borderColor: "var(--border)", backgroundColor: "rgba(10,10,12,0.8)", backdropFilter: "blur(12px)" }}>
          <div className="flex items-center gap-4">
            <div className="text-right hidden sm:block">
              <p className="text-sm font-bold" style={{ color: "var(--text-primary)" }}>{user?.github_login || "User"}</p>
              <p className="text-[10px] font-bold uppercase tracking-wider" style={{ color: "var(--accent)" }}>Maintainer</p>
            </div>
            <div className="w-10 h-10 rounded-full overflow-hidden" style={{ background: "linear-gradient(135deg, var(--accent-dark), var(--accent))", padding: "1px" }}>
              <div className="w-full h-full overflow-hidden" style={{ backgroundColor: "var(--bg-primary)" }}>
                {user?.avatar_url ? (
                  <img src={user.avatar_url} alt="avatar" className="w-full h-full object-cover" />
                ) : (
                  <img src="https://api.dicebear.com/7.x/avataaars/svg?seed=user" alt="avatar" />
                )}
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
