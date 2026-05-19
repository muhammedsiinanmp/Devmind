import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import apiClient from "../api/client";
import {
  Shield, AlertTriangle, XCircle, CheckCircle, FileCode,
  RefreshCw, ArrowLeft, Loader2, Activity, Play
} from "lucide-react";

interface ScanResult {
  id: number;
  repository: number;
  repository_name: string;
  status: "queued" | "scanning" | "completed" | "failed";
  progress: number;
  total_files: number;
  files_scanned: number;
  total_issues: number;
  critical_count: number;
  warning_count: number;
  info_count: number;
  scan_duration_ms: number | null;
  created_at: string;
  completed_at: string | null;
}

export default function ScanReport() {
  const { id } = useParams<{ id: string }>();
  const [scan, setScan] = useState<ScanResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [triggering, setTriggering] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const fetchScan = async (scanId: number) => {
    try {
      const res = await apiClient.get<ScanResult>(`/scans/${scanId}/`);
      setScan(res.data);
      setError(null);
    } catch {
      setError("No scan found for this repository.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (id) {
      const numId = parseInt(id, 10);
      if (numId > 10000) {
        fetchScan(numId);
      } else {
        setError("Scan ID not recognized.");
        setLoading(false);
      }
    } else {
      setError("No scan ID provided.");
      setLoading(false);
    }
  }, [id]);

  const handleRefresh = async () => {
    if (!scan) return;
    setRefreshing(true);
    await fetchScan(scan.id);
    setRefreshing(false);
  };

  const handleTriggerScan = async () => {
    if (!id) return;
    setTriggering(true);
    try {
      await apiClient.post(`/repositories/${id}/scan/`);
      alert("Scan queued. Wait a moment and refresh to see results.");
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { error?: string } } })?.response?.data?.error || "Failed to trigger scan";
      alert(msg);
    } finally {
      setTriggering(false);
    }
  };

  const statusColor = (status: string) => {
    switch (status) {
      case "completed": return "var(--success)";
      case "failed": return "var(--error)";
      case "scanning": case "queued": return "var(--warning)";
      default: return "var(--text-muted)";
    }
  };

  if (loading) {
    return (
      <div className="min-h-[60vh] flex flex-col items-center justify-center space-y-4">
        <Loader2 className="w-10 h-10 animate-spin" style={{ color: "var(--accent)" }} />
        <p className="animate-pulse" style={{ color: "var(--text-secondary)" }}>Analyzing repository health...</p>
      </div>
    );
  }

  return (
    <div className="space-y-8 animate-fade-in pb-20">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-4xl font-bold mb-2 text-gradient">Health Report</h1>
          <p className="text-lg" style={{ color: "var(--text-secondary)" }}>
            Full repository security and quality scan results.
          </p>
        </div>
        <div className="flex items-center gap-3">
          {scan && (
            <button onClick={handleRefresh} disabled={refreshing} className="btn-secondary flex items-center gap-2">
              <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin' : ''}`} />
              {refreshing ? "Refreshing..." : "Refresh"}
            </button>
          )}
          {id && (
            <button onClick={handleTriggerScan} disabled={triggering} className="btn-primary flex items-center gap-2">
              {triggering ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
              {triggering ? "Queuing..." : "New Scan"}
            </button>
          )}
        </div>
      </div>

      {error && (
        <div className="glass-card p-8 text-center space-y-4">
          <div className="w-16 h-16 rounded-2xl flex items-center justify-center border mx-auto" style={{ backgroundColor: "var(--bg-tertiary)", borderColor: "var(--border)" }}>
            <AlertTriangle className="w-8 h-8" style={{ color: "var(--text-muted)" }} />
          </div>
          <h3 className="text-xl font-semibold" style={{ color: "var(--text-primary)" }}>{error}</h3>
          {id && (
            <button onClick={handleTriggerScan} className="btn-primary">
              <Play className="w-4 h-4" /> Trigger a Scan
            </button>
          )}
          <Link to="/repositories" className="btn-secondary mt-2">
            <ArrowLeft className="w-4 h-4" /> Back to Repositories
          </Link>
        </div>
      )}

      {scan && (() => {
        const healthScore = Math.max(0, 100 - (scan.critical_count * 10) - (scan.warning_count * 5) - (scan.info_count * 1));
        const gaugeColor = healthScore >= 70 ? "var(--success)" : healthScore >= 40 ? "var(--warning)" : "var(--error)";
        const gaugeLabel = healthScore >= 70 ? "Healthy" : healthScore >= 40 ? "Needs Attention" : "Critical";

        return (
        <>
          {scan.status === "completed" && (
            <div className="flex justify-center">
              <div className="glass-card p-8 flex flex-col items-center gap-4" style={{ minWidth: 200 }}>
                <span className="text-xs font-bold uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>Health Score</span>
                <div style={{ position: "relative", width: 120, height: 120 }}>
                  <svg viewBox="0 0 36 36" style={{ transform: "rotate(-90deg)", width: 120, height: 120 }}>
                    <path
                      d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                      fill="none"
                      stroke="var(--bg-tertiary)"
                      strokeWidth="3"
                    />
                    <path
                      d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                      fill="none"
                      stroke={gaugeColor}
                      strokeWidth="3"
                      strokeDasharray={`${healthScore}, 100`}
                      strokeLinecap="round"
                    />
                  </svg>
                  <div style={{
                    position: "absolute", top: "50%", left: "50%",
                    transform: "translate(-50%, -50%)",
                    fontSize: "1.5rem", fontWeight: "bold",
                    color: gaugeColor
                  }}>
                    {healthScore}
                  </div>
                </div>
                <span className="text-sm" style={{ color: "var(--text-secondary)" }}>
                  {gaugeLabel}
                </span>
              </div>
            </div>
          )}

          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div className="glass-card p-8" style={{ background: "linear-gradient(135deg, rgba(16,185,129,0.05) 0%, transparent 100%)", borderColor: "rgba(16,185,129,0.2)" }}>
              <div className="flex items-center gap-3 mb-4">
                <Shield className="w-6 h-6" style={{ color: "var(--success)" }} />
                <span className="text-xs font-bold uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>Total Issues</span>
              </div>
              <div className="text-5xl font-bold" style={{ color: "var(--text-primary)" }}>{scan.total_issues}</div>
              <p className="text-xs mt-2" style={{ color: "var(--text-muted)" }}>{scan.critical_count} critical, {scan.warning_count} warnings, {scan.info_count} info</p>
            </div>

            <div className="glass-card p-8">
              <div className="flex items-center gap-3 mb-4">
                <FileCode className="w-6 h-6" style={{ color: "var(--warning)" }} />
                <span className="text-xs font-bold uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>Files Scanned</span>
              </div>
              <div className="text-5xl font-bold" style={{ color: "var(--text-primary)" }}>
                {scan.files_scanned}<span className="text-xl" style={{ color: "var(--text-muted)" }}>/{scan.total_files}</span>
              </div>
              {scan.progress > 0 && (
                <div className="w-full h-1.5 rounded-full mt-3 overflow-hidden" style={{ backgroundColor: "var(--bg-tertiary)" }}>
                  <div className="h-full" style={{ width: `${scan.progress}%`, backgroundColor: "var(--accent)" }} />
                </div>
              )}
            </div>

            <div className="glass-card p-8">
              <div className="flex items-center gap-3 mb-4">
                <Activity className="w-6 h-6" style={{ color: "var(--accent)" }} />
                <span className="text-xs font-bold uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>Status</span>
              </div>
              <div className="text-3xl font-bold capitalize" style={{ color: statusColor(scan.status) }}>{scan.status}</div>
              <p className="text-xs mt-2" style={{ color: "var(--text-muted)" }}>
                {scan.created_at ? `Started ${new Date(scan.created_at).toLocaleString()}` : "Not started"}
              </p>
            </div>
          </div>

          {(scan.status === "queued" || scan.status === "scanning") && (
            <div className="glass-card p-6 border-l-4" style={{ borderColor: "var(--warning)", backgroundColor: "rgba(245,158,11,0.05)" }}>
              <div className="flex items-center gap-3">
                <Loader2 className="w-5 h-5 animate-spin" style={{ color: "var(--warning)" }} />
                <p style={{ color: "var(--text-secondary)" }}>
                  Scan {scan.status === "queued" ? "is queued" : "is scanning"} — {scan.progress}% complete.
                </p>
              </div>
            </div>
          )}

          {scan.status === "completed" && (
            <div className="glass-card p-6 border-l-4" style={{ borderColor: "var(--success)", backgroundColor: "rgba(16,185,129,0.05)" }}>
              <div className="flex items-center gap-3">
                <CheckCircle className="w-5 h-5" style={{ color: "var(--success)" }} />
                <p style={{ color: "var(--text-secondary)" }}>
                  Scan completed. {scan.total_issues} issues found across {scan.files_scanned} files.
                </p>
              </div>
            </div>
          )}

          <div className="flex flex-wrap gap-4">
            {scan.critical_count > 0 && (
              <div className="glass-card px-6 py-4 flex items-center gap-3" style={{ borderColor: "rgba(239,68,68,0.2)" }}>
                <XCircle className="w-5 h-5" style={{ color: "var(--error)" }} />
                <span className="font-bold" style={{ color: "var(--error)" }}>{scan.critical_count} Critical</span>
              </div>
            )}
            {scan.warning_count > 0 && (
              <div className="glass-card px-6 py-4 flex items-center gap-3" style={{ borderColor: "rgba(245,158,11,0.2)" }}>
                <AlertTriangle className="w-5 h-5" style={{ color: "var(--warning)" }} />
                <span className="font-bold" style={{ color: "var(--warning)" }}>{scan.warning_count} Warnings</span>
              </div>
            )}
            {scan.info_count > 0 && (
              <div className="glass-card px-6 py-4 flex items-center gap-3" style={{ borderColor: "rgba(139,92,246,0.2)" }}>
                <FileCode className="w-5 h-5" style={{ color: "var(--accent)" }} />
                <span className="font-bold" style={{ color: "var(--accent)" }}>{scan.info_count} Info</span>
              </div>
            )}
          </div>
        </>
        );
      })()}
    </div>
  );
}
