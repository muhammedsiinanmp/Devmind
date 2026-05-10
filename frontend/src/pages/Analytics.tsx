import { BarChart3, TrendingUp, Shield, Zap } from "lucide-react";

export default function Analytics() {
  return (
    <div className="space-y-8 animate-fade-in">
      <div>
        <h1 className="text-4xl font-bold text-gradient mb-2">Analytics</h1>
        <p className="text-text-secondary text-lg">
          Insights into your repository health and security posture.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        {[
          { label: "Total Scans", value: "0", icon: Zap, color: "text-accent" },
          { label: "Issues Fixed", value: "0", icon: TrendingUp, color: "text-success" },
          { label: "Security Risk", value: "Safe", icon: Shield, color: "text-info" },
          { label: "Review Latency", value: "0ms", icon: BarChart3, color: "text-warning" },
        ].map((stat, i) => (stat && (
          <div key={i} className="glass-card p-6 space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-[10px] uppercase font-bold text-text-muted tracking-widest">{stat.label}</span>
              <stat.icon className={`w-4 h-4 ${stat.color}`} />
            </div>
            <p className="text-2xl font-bold text-white">{stat.value}</p>
          </div>
        )))}
      </div>

      <div className="glass-card p-20 text-center flex flex-col items-center justify-center space-y-6">
        <div className="w-20 h-20 bg-accent/10 rounded-full flex items-center justify-center border border-accent/20 animate-pulse">
          <BarChart3 className="w-10 h-10 text-accent" />
        </div>
        <div className="space-y-2">
          <h2 className="text-2xl font-bold text-white">Analytics Engine Spooling Up</h2>
          <p className="text-text-secondary max-w-md mx-auto">
            We are collecting data from your initial reviews. Advanced charts, trend analysis, and team performance metrics will appear here shortly.
          </p>
        </div>
        <div className="flex gap-4">
          <div className="px-4 py-2 rounded-lg bg-bg-tertiary border border-border text-xs font-bold uppercase tracking-wider text-text-muted">
            Phase 3: Insights
          </div>
        </div>
      </div>
    </div>
  );
}
