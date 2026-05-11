import { BarChart3 } from "lucide-react";

export default function Analytics() {
  return (
    <div className="space-y-8 animate-fade-in">
      <div>
        <h1 className="text-4xl font-bold mb-2 text-gradient">Analytics</h1>
        <p className="text-lg" style={{ color: "var(--text-secondary)" }}>
          Security trends and code quality metrics across your repositories.
        </p>
      </div>

      <div className="glass-card p-12 text-center flex flex-col items-center justify-center space-y-4">
        <div className="w-16 h-16 rounded-2xl flex items-center justify-center border" style={{ backgroundColor: "var(--bg-tertiary)", borderColor: "var(--border)" }}>
          <BarChart3 className="w-8 h-8" style={{ color: "var(--text-muted)" }} />
        </div>
        <h3 className="text-xl font-semibold" style={{ color: "var(--text-primary)" }}>Coming Soon</h3>
        <p style={{ color: "var(--text-secondary)" }}>
          Analytics and metrics dashboard is currently under development. Check back soon for security trends and code quality insights.
        </p>
      </div>
    </div>
  );
}
