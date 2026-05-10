import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { scanApi, ScanResult, ScanFinding } from "../api/scan";
import {
  Shield,
  AlertTriangle,
  XCircle,
  CheckCircle,
  FileCode,
  RefreshCw,
  ArrowLeft,
  Loader2,
  Activity,
  Zap
} from "lucide-react";

export default function ScanReport() {
  const { id } = useParams<{ id: string }>();
  const [scan, setScan] = useState<ScanResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchScan = async () => {
    if (!id) return;
    setLoading(true);
    setError(null);
    try {
      const result = await scanApi.getLatestScan(parseInt(id));
      setScan(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load scan");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchScan();
  }, [id]);

  const getSeverityColor = (severity: string) => {
    switch (severity) {
      case "critical": return "text-error";
      case "error": return "text-orange-500";
      case "warning": return "text-warning";
      default: return "text-info";
    }
  };

  const groupFindingsByCategory = (findings: ScanFinding[]) => {
    const grouped: Record<string, ScanFinding[]> = {};
    findings.forEach((f) => {
      if (!grouped[f.category]) grouped[f.category] = [];
      grouped[f.category].push(f);
    });
    return grouped;
  };

  if (loading) {
    return (
      <div className="min-h-[60vh] flex flex-col items-center justify-center space-y-4">
        <Loader2 className="w-10 h-10 animate-spin text-accent" />
        <p className="text-text-secondary animate-pulse">Analyzing repository health...</p>
      </div>
    );
  }

  if (error || !scan) {
    return (
      <div className="glass-card p-12 text-center flex flex-col items-center justify-center space-y-4">
        <AlertTriangle className="w-12 h-12 text-error" />
        <h3 className="text-xl font-semibold">{error || "No scan found"}</h3>
        <Link to="/repositories" className="btn-secondary flex items-center gap-2">
          <ArrowLeft className="w-4 h-4" /> Back to Repositories
        </Link>
      </div>
    );
  }

  const groupedFindings = groupFindingsByCategory(scan.findings || []);

  return (
    <div className="space-y-8 animate-fade-in pb-20">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-4xl font-bold text-gradient mb-2">Health Report</h1>
          <p className="text-text-secondary text-lg">
            Full repository security and quality scan results.
          </p>
        </div>
        <button
          onClick={fetchScan}
          className="btn-secondary flex items-center gap-2"
        >
          <RefreshCw className="w-4 h-4" />
          Refresh Report
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="glass-card p-8 bg-gradient-to-br from-success/5 to-transparent border-success/20">
          <div className="flex items-center gap-3 mb-4">
            <Shield className="w-6 h-6 text-success" />
            <span className="text-xs font-bold text-text-muted uppercase tracking-wider">Health Score</span>
          </div>
          <div className="text-5xl font-bold text-success">
            {scan.health_score ?? "—"}<span className="text-xl text-text-muted">/100</span>
          </div>
          <p className="text-xs text-text-muted mt-2">Based on issue density and severity.</p>
        </div>

        <div className="glass-card p-8">
          <div className="flex items-center gap-3 mb-4">
            <AlertTriangle className="w-6 h-6 text-warning" />
            <span className="text-xs font-bold text-text-muted uppercase tracking-wider">Total Findings</span>
          </div>
          <div className="text-5xl font-bold text-white">
            {scan.findings?.length ?? 0}
          </div>
          <p className="text-xs text-text-muted mt-2">Issues detected across the codebase.</p>
        </div>

        <div className="glass-card p-8">
          <div className="flex items-center gap-3 mb-4">
            <Activity className="w-6 h-6 text-accent" />
            <span className="text-xs font-bold text-text-muted uppercase tracking-wider">Scan Status</span>
          </div>
          <div className="text-4xl font-bold text-white capitalize">
            {scan.status}
          </div>
          <p className="text-xs text-text-muted mt-2">Analysis completed {new Date().toLocaleTimeString()}.</p>
        </div>
      </div>

      {scan.summary && (
        <section className="glass-card p-6 border-l-4 border-l-accent">
          <div className="flex items-center gap-2 mb-4">
            <Zap className="w-5 h-5 text-accent" />
            <h2 className="text-lg font-bold text-white">AI Overview</h2>
          </div>
          <p className="text-text-secondary leading-relaxed italic">
            "{scan.summary}"
          </p>
        </section>
      )}

      <div className="space-y-6">
        {Object.entries(groupedFindings).map(([category, findings]) => (
          <div key={category} className="glass-card overflow-hidden">
            <div className="px-6 py-4 bg-white/5 border-b border-border flex items-center justify-between">
              <h2 className="font-bold text-white capitalize flex items-center gap-2">
                <FileCode className="w-4 h-4 text-accent" /> {category}
              </h2>
              <span className="badge badge-info">{findings.length} findings</span>
            </div>
            <div className="divide-y divide-border/50">
              {findings.map((finding) => (
                <div key={finding.id} className="px-6 py-6 hover:bg-white/5 transition-colors group">
                  <div className="flex items-start gap-4">
                    <div className="mt-1">
                      {finding.severity === 'critical' ? <XCircle className="w-5 h-5 text-error" /> : <AlertTriangle className="w-5 h-5 text-warning" />}
                    </div>
                    <div className="flex-1 space-y-2">
                      <div className="flex flex-wrap items-center gap-3">
                        <code className="text-xs font-mono text-accent bg-accent/5 px-2 py-1 rounded border border-accent/10">
                          {finding.file_path}
                          {finding.line_number && `:${finding.line_number}`}
                        </code>
                        <span className={`text-[10px] uppercase font-bold px-2 py-0.5 rounded bg-bg-tertiary ${getSeverityColor(finding.severity)}`}>
                          {finding.severity}
                        </span>
                      </div>
                      <p className="text-text-primary leading-relaxed">{finding.message}</p>
                      {finding.rule_id && (
                        <p className="text-[10px] text-text-muted font-bold uppercase tracking-wider">
                          Policy: {finding.rule_id}
                        </p>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
