import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuthStore } from "../store/index";
import { Loader2, AlertCircle } from "lucide-react";

export default function AuthCallback() {
  const [error, setError] = useState<string | null>(null);
  const setTokens = useAuthStore((state) => state.setTokens);
  const navigate = useNavigate();

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");
    const state = params.get("state");

    if (!code || !state) {
      navigate("/login", { replace: true });
      return;
    }

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);

    fetch(`/api/v1/auth/github/callback/?code=${code}&state=${state}`, {
      signal: controller.signal,
    })
      .then((res) => {
        clearTimeout(timeout);
        return res.json();
      })
      .then((data) => {
        if (data.access && data.refresh) {
          setTokens(data.access, data.refresh);
          window.history.replaceState({}, "", "/auth/callback");
          navigate("/dashboard", { replace: true });
        } else {
          setError(data.error || "Authentication failed. Please try again.");
        }
      })
      .catch((err) => {
        clearTimeout(timeout);
        if (err instanceof DOMException && err.name === "AbortError") {
          setError("Request timed out. Please check your connection and try again.");
        } else {
          setError("Authentication failed. Please try again.");
        }
      });
  }, []);

  if (error) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center" style={{ backgroundColor: "var(--bg-primary)" }}>
        <div className="glass-card p-8 text-center max-w-md space-y-4">
          <div className="w-12 h-12 flex items-center justify-center mx-auto" style={{ backgroundColor: "rgba(239,68,68,0.1)", border: "1px solid rgba(239,68,68,0.2)" }}>
            <AlertCircle className="w-6 h-6" style={{ color: "var(--error)" }} />
          </div>
          <h2 className="text-xl font-bold" style={{ color: "var(--text-primary)" }}>Authentication Failed</h2>
          <p className="text-sm" style={{ color: "var(--text-secondary)" }}>{error}</p>
          <button
            onClick={() => navigate("/login", { replace: true })}
            className="px-6 py-3 font-bold transition-all"
            style={{ backgroundColor: "var(--accent)", color: "white" }}
          >
            Back to Login
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex flex-col items-center justify-center" style={{ backgroundColor: "var(--bg-primary)" }}>
      <div className="flex flex-col items-center space-y-4">
        <Loader2 className="w-10 h-10 animate-spin" style={{ color: "var(--accent)" }} />
        <p className="font-medium animate-pulse" style={{ color: "var(--text-secondary)" }}>
          Connecting to GitHub...
        </p>
      </div>
    </div>
  );
}
