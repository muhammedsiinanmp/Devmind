import { useEffect, useState } from "react";
import { useAuthStore } from "../store/index";
import { useNavigate } from "react-router-dom";
import { GitBranch, Terminal, Shield, Zap, Code2, ArrowRight, Loader2 } from "lucide-react";

export default function Login() {
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const setTokens = useAuthStore((state) => state.setTokens);
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const navigate = useNavigate();

  useEffect(() => {
    if (isAuthenticated) {
      navigate("/dashboard", { replace: true });
    }
  }, [isAuthenticated, navigate]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");
    const state = params.get("state");

    if (code && state) {
      handleCallback(code, state);
    }
  }, []);

  const handleCallback = async (code: string, state: string) => {
    setIsLoading(true);
    try {
      const res = await fetch(`/api/v1/auth/github/callback/?code=${code}&state=${state}`);
      const data = await res.json();

      if (data.access && data.refresh) {
        setTokens(data.access, data.refresh);
        const cleanUrl = window.location.pathname;
        window.history.replaceState({}, "", cleanUrl);
        navigate("/dashboard", { replace: true });
      } else if (data.error) {
        setError(data.error);
        setIsLoading(false);
      }
    } catch {
      setError("Authentication failed. Please try again.");
      setIsLoading(false);
    }
  };

  const handleGitHubLogin = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/v1/auth/github/start/");
      const data = await res.json();

      if (data.authorize_url) {
        window.location.href = data.authorize_url;
      } else {
        throw new Error();
      }
    } catch {
      setError("Could not connect to GitHub. Please try again.");
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex flex-col relative overflow-hidden" style={{ backgroundColor: "var(--bg-primary)" }}>
      <div className="absolute top-0 left-0 w-full h-full overflow-hidden pointer-events-none">
        <div className="absolute top-[-10%] left-[-10%] w-[40%] h-[40%] rounded-full opacity-10 blur-[120px]" style={{ backgroundColor: "var(--accent)" }} />
        <div className="absolute bottom-[-10%] right-[-10%] w-[40%] h-[40%] rounded-full opacity-10 blur-[120px]" style={{ backgroundColor: "var(--accent-dark)" }} />
      </div>

      <header className="relative z-10 p-8 flex items-center justify-between max-w-7xl mx-auto w-full">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl flex items-center justify-center shadow-accent" style={{ background: "linear-gradient(135deg, var(--accent) 0%, var(--accent-dark) 100%)" }}>
            <Terminal className="text-white w-6 h-6" />
          </div>
          <span className="text-xl font-bold tracking-tight" style={{ color: "var(--text-primary)" }}>DevMind</span>
        </div>
      </header>

      <main className="relative z-10 flex-1 flex flex-col items-center justify-center px-4 py-12 text-center max-w-4xl mx-auto">
        <div className="space-y-6 animate-fade-in">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-bold uppercase tracking-widest" style={{ backgroundColor: "rgba(139,92,246,0.1)", border: "1px solid rgba(139,92,246,0.2)", color: "var(--accent)" }}>
            <Zap className="w-3 h-3" /> Now in Beta
          </div>
          <h1 className="text-6xl md:text-7xl font-bold tracking-tight leading-tight" style={{ color: "var(--text-primary)" }}>
            AI Code Reviews that <br />
            <span style={{ background: "linear-gradient(135deg, var(--accent-light) 0%, var(--accent) 100%)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", backgroundClip: "text" }}>Feel Human.</span>
          </h1>
          <p className="text-xl max-w-2xl mx-auto leading-relaxed" style={{ color: "var(--text-secondary)" }}>
            Connect your GitHub repositories and get instant, high-fidelity security and quality audits on every pull request.
          </p>

          <div className="pt-8">
            <button
              onClick={handleGitHubLogin}
              disabled={isLoading}
              className="group relative inline-flex items-center gap-3 px-8 py-4 rounded-2xl font-bold text-lg transition-all duration-300 shadow-xl"
              style={{
                background: "white",
                color: "var(--bg-primary)",
                boxShadow: "0 4px 12px rgba(139,92,246,0.25)",
              }}
            >
              {isLoading ? (
                <Loader2 className="w-6 h-6 animate-spin" />
              ) : (
                <>
                  <GitBranch className="w-6 h-6" />
                  Continue with GitHub
                  <ArrowRight className="w-5 h-5 group-hover:translate-x-1 transition-transform" />
                </>
              )}
            </button>
            {error && (
              <p className="mt-4 font-medium text-sm rounded-lg inline-block px-4 py-2" style={{ backgroundColor: "rgba(239,68,68,0.1)", border: "1px solid rgba(239,68,68,0.2)", color: "var(--error)" }}>
                {error}
              </p>
            )}
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 pt-20">
            {[
              { icon: Shield, title: "Security First", desc: "Detects vulnerabilities and sensitive data leaks before merge." },
              { icon: Code2, title: "Quality Guards", desc: "Enforces best practices, readability, and architectural patterns." },
              { icon: Zap, title: "Instant Feedback", desc: "AI reviews delivered in seconds, right in your PR comments." },
            ].map(({ icon: Icon, title, desc }) => (
              <div key={title} className="glass-card p-6 text-left space-y-3" style={{ background: "linear-gradient(135deg, rgba(255,255,255,0.05) 0%, rgba(255,255,255,0.01) 100%)", border: "1px solid var(--border)", borderRadius: "16px" }}>
                <div className="w-10 h-10 rounded-lg flex items-center justify-center" style={{ backgroundColor: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.1)" }}>
                  <Icon className="w-5 h-5" style={{ color: "var(--accent)" }} />
                </div>
                <h3 className="font-bold" style={{ color: "var(--text-primary)" }}>{title}</h3>
                <p className="text-sm" style={{ color: "var(--text-secondary)" }}>{desc}</p>
              </div>
            ))}
          </div>
        </div>
      </main>

      <footer className="relative z-10 p-8 border-t mt-12" style={{ borderColor: "var(--border)", backgroundColor: "rgba(20,20,24,0.5)" }}>
        <div className="max-w-7xl mx-auto flex flex-col md:flex-row items-center justify-between gap-4 text-sm font-medium" style={{ color: "var(--text-muted)" }}>
          <p>© 2026 DevMind AI. Built for elite engineering teams.</p>
          <div className="flex items-center gap-6">
            {["Privacy", "Terms", "Documentation"].map(link => (
              <a key={link} href="#" className="hover:opacity-100 transition-opacity" style={{ opacity: 0.6 }}>{link}</a>
            ))}
          </div>
        </div>
      </footer>
    </div>
  );
}
