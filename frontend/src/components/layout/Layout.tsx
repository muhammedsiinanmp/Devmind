import { Link, useLocation } from "react-router-dom";
import { useAuthStore } from "../../store/index";
import { LayoutDashboard, GitBranch, Settings, BarChart3, LogOut, Terminal } from "lucide-react";
import { useEffect, useState } from "react";
import apiClient from "../../api/client";

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
    apiClient.get<UserProfile>("/auth/me/")
      .then(res => setUser(res.data))
      .catch(() => {});
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
    <div className="min-h-screen" style={{ backgroundColor: "var(--bg-primary)", color: "var(--text-primary)" }}>
      <nav className="border-b sticky top-0 z-50" style={{ borderColor: "var(--border)", backgroundColor: "var(--bg-secondary)" }}>
        <div className="max-w-7xl mx-auto px-4 sm:px-8 flex items-center h-16 gap-6">
          <Link to="/dashboard" className="flex items-center gap-3 flex-shrink-0">
            <div className="w-8 h-8 flex items-center justify-center" style={{ background: "var(--accent)" }}>
              <Terminal className="text-white w-5 h-5" />
            </div>
            <span className="text-lg font-bold tracking-tight" style={{ color: "var(--text-primary)" }}>DevMind</span>
          </Link>

          <div className="flex items-center gap-1 ml-auto">
            {navItems.map((item) => (
              <Link
                key={item.path}
                to={item.path}
                className="flex items-center gap-2 px-3 py-2 text-sm font-medium transition-all"
                style={isActive(item.path)
                  ? { backgroundColor: "rgba(139,92,246,0.1)", color: "var(--accent)" }
                  : { color: "var(--text-secondary)" }
                }
              >
                <item.icon className="w-4 h-4" />
                <span className="hidden sm:inline">{item.label}</span>
              </Link>
            ))}
          </div>

          <div className="flex items-center gap-4 flex-shrink-0">
            <div className="text-right hidden sm:block">
              <p className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>{user?.github_login || "User"}</p>
            </div>
            <div className="w-8 h-8 overflow-hidden" style={{ border: "1px solid var(--accent)" }}>
              <div className="w-full h-full" style={{ backgroundColor: "var(--bg-primary)" }}>
                {user?.avatar_url ? (
                  <img src={user.avatar_url} alt="avatar" className="w-full h-full object-cover" />
                ) : (
                  <div className="w-full h-full" style={{ backgroundColor: "var(--bg-tertiary)" }} />
                )}
              </div>
            </div>
            <button onClick={handleLogout} className="p-2 transition-colors" style={{ color: "var(--text-muted)" }} title="Logout">
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        </div>
      </nav>

      <main className="max-w-7xl mx-auto px-4 sm:px-8 py-8">
        {children}
      </main>
    </div>
  );
}
