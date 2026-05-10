import { useState } from "react";
import { useAuthStore } from "../store/index";
import { GitBranch, Terminal, Shield, Zap, Code2, ArrowRight, Loader2 } from "lucide-react";

export default function Login() {
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleGitHubLogin = async () => {
    setIsLoading(true);
    setError(null);
    try {
      // Direct GitHub OAuth initiation
      window.location.href = `${import.meta.env.VITE_API_URL || ""}/api/v1/auth/github/login/`;
    } catch (err) {
      setError("Could not connect to GitHub. Please try again.");
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-bg-primary flex flex-col relative overflow-hidden">
      {/* Animated Background Elements */}
      <div className="absolute top-0 left-0 w-full h-full overflow-hidden pointer-events-none">
        <div className="absolute top-[-10%] left-[-10%] w-[40%] h-[40%] rounded-full bg-accent/10 blur-[120px]" />
        <div className="absolute bottom-[-10%] right-[-10%] w-[40%] h-[40%] rounded-full bg-accent-dark/10 blur-[120px]" />
      </div>

      {/* Header */}
      <header className="relative z-10 p-8 flex items-center justify-between max-w-7xl mx-auto w-full">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-accent to-accent-dark flex items-center justify-center shadow-accent">
            <Terminal className="text-white w-6 h-6" />
          </div>
          <span className="text-xl font-bold tracking-tight text-white">DevMind</span>
        </div>
      </header>

      {/* Hero Content */}
      <main className="relative z-10 flex-1 flex flex-col items-center justify-center px-4 py-12 text-center max-w-4xl mx-auto">
        <div className="space-y-6 animate-fade-in">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-accent/10 border border-accent/20 text-accent text-xs font-bold uppercase tracking-widest">
            <Zap className="w-3 h-3" /> Now in Beta
          </div>
          <h1 className="text-6xl md:text-7xl font-bold tracking-tight leading-tight">
            AI Code Reviews that <br />
            <span className="text-accent-gradient">Feel Human.</span>
          </h1>
          <p className="text-xl text-text-secondary max-w-2xl mx-auto leading-relaxed">
            Connect your GitHub repositories and get instant, high-fidelity security and quality audits on every pull request.
          </p>

          <div className="pt-8">
            <button
              onClick={handleGitHubLogin}
              disabled={isLoading}
              className="group relative inline-flex items-center gap-3 bg-white text-bg-primary px-8 py-4 rounded-2xl font-bold text-lg hover:bg-accent hover:text-white transition-all duration-300 shadow-xl hover:shadow-accent/40"
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
              <p className="mt-4 text-error font-medium text-sm bg-error/10 py-2 px-4 rounded-lg inline-block border border-error/20">
                {error}
              </p>
            )}
          </div>

          {/* Features Grid */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 pt-20">
            <div className="glass-card p-6 text-left space-y-3">
              <div className="w-10 h-10 rounded-lg bg-white/5 flex items-center justify-center border border-white/10">
                <Shield className="w-5 h-5 text-accent" />
              </div>
              <h3 className="font-bold text-white">Security First</h3>
              <p className="text-sm text-text-secondary">Detects vulnerabilities and sensitive data leaks before merge.</p>
            </div>
            <div className="glass-card p-6 text-left space-y-3">
              <div className="w-10 h-10 rounded-lg bg-white/5 flex items-center justify-center border border-white/10">
                <Code2 className="w-5 h-5 text-accent" />
              </div>
              <h3 className="font-bold text-white">Quality Guards</h3>
              <p className="text-sm text-text-secondary">Enforces best practices, readability, and architectural patterns.</p>
            </div>
            <div className="glass-card p-6 text-left space-y-3">
              <div className="w-10 h-10 rounded-lg bg-white/5 flex items-center justify-center border border-white/10">
                <Zap className="w-5 h-5 text-accent" />
              </div>
              <h3 className="font-bold text-white">Instant Feedback</h3>
              <p className="text-sm text-text-secondary">AI reviews delivered in seconds, right in your PR comments.</p>
            </div>
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="relative z-10 p-8 border-t border-border mt-12 bg-bg-secondary/50">
        <div className="max-w-7xl mx-auto flex flex-col md:flex-row items-center justify-between gap-4 text-text-muted text-sm font-medium">
          <p>© 2026 DevMind AI. Built for elite engineering teams.</p>
          <div className="flex items-center gap-6">
            <a href="#" className="hover:text-white transition-colors">Privacy</a>
            <a href="#" className="hover:text-white transition-colors">Terms</a>
            <a href="#" className="hover:text-white transition-colors">Documentation</a>
          </div>
        </div>
      </footer>
    </div>
  );
}
