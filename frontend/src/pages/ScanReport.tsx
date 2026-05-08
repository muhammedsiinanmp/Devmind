import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { scanApi, ScanResult, ScanFinding } from "../api/scan";
import { Shield, AlertTriangle, XCircle, CheckCircle, FileCode, RefreshCw } from "lucide-react";

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

  const getHealthColor = (score: number | null) => {
    if (score === null) return "text-gray-500";
    if (score >= 70) return "text-green-600";
    if (score >= 40) return "text-yellow-600";
    return "text-red-600";
  };

  const getHealthBg = (score: number | null) => {
    if (score === null) return "bg-gray-100";
    if (score >= 70) return "bg-green-100";
    if (score >= 40) return "bg-yellow-100";
    return "bg-red-100";
  };

  const getSeverityIcon = (severity: string) => {
    switch (severity) {
      case "critical":
        return <XCircle className="w-4 h-4 text-red-600" />;
      case "error":
        return <AlertTriangle className="w-4 h-4 text-orange-600" />;
      case "warning":
        return <AlertTriangle className="w-4 h-4 text-yellow-600" />;
      default:
        return <CheckCircle className="w-4 h-4 text-blue-600" />;
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
      <div className="p-6">
        <div className="animate-pulse space-y-4">
          <div className="h-32 bg-gray-200 rounded-lg" />
          <div className="h-64 bg-gray-200 rounded-lg" />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6">
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-red-700">
          {error}
        </div>
        <button
          onClick={fetchScan}
          className="mt-4 px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700"
        >
          Retry
        </button>
      </div>
    );
  }

  if (!scan) {
    return (
      <div className="p-6">
        <div className="bg-gray-50 border border-gray-200 rounded-lg p-8 text-center">
          <Shield className="w-12 h-12 mx-auto text-gray-400 mb-4" />
          <h3 className="text-lg font-medium text-gray-900">No scan found</h3>
          <p className="text-gray-500 mt-2">Trigger a scan to see the report</p>
        </div>
      </div>
    );
  }

  const groupedFindings = groupFindingsByCategory(scan.findings || []);

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Scan Report</h1>
        <button
          onClick={fetchScan}
          className="flex items-center gap-2 px-4 py-2 text-sm bg-gray-100 hover:bg-gray-200 rounded-lg"
        >
          <RefreshCw className="w-4 h-4" />
          Refresh
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-6">
        <div className={`p-6 rounded-lg ${getHealthBg(scan.health_score)}`}>
          <div className="flex items-center gap-3 mb-2">
            <Shield className={`w-6 h-6 ${getHealthColor(scan.health_score)}`} />
            <span className="text-sm font-medium text-gray-600">Health Score</span>
          </div>
          <div className={`text-4xl font-bold ${getHealthColor(scan.health_score)}`}>
            {scan.health_score ?? "—"}
          </div>
        </div>

        <div className="bg-white border rounded-lg p-6">
          <div className="flex items-center gap-3 mb-2">
            <AlertTriangle className="w-6 h-6 text-orange-500" />
            <span className="text-sm font-medium text-gray-600">Issues Found</span>
          </div>
          <div className="text-4xl font-bold text-gray-900">
            {scan.findings?.length ?? 0}
          </div>
        </div>

        <div className="bg-white border rounded-lg p-6">
          <div className="flex items-center gap-3 mb-2">
            <FileCode className="w-6 h-6 text-blue-500" />
            <span className="text-sm font-medium text-gray-600">Status</span>
          </div>
          <div className="text-4xl font-bold text-gray-900 capitalize">
            {scan.status}
          </div>
        </div>
      </div>

      {scan.summary && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-6">
          <h3 className="font-medium text-blue-900">Summary</h3>
          <p className="text-blue-800 mt-1">{scan.summary}</p>
        </div>
      )}

      <div className="space-y-6">
        {Object.entries(groupedFindings).map(([category, findings]) => (
          <div key={category} className="bg-white border rounded-lg overflow-hidden">
            <div className="bg-gray-50 px-6 py-3 border-b">
              <h2 className="font-semibold text-gray-900 capitalize">{category}</h2>
              <span className="text-sm text-gray-500">{findings.length} findings</span>
            </div>
            <div className="divide-y">
              {findings.map((finding) => (
                <div key={finding.id} className="px-6 py-4">
                  <div className="flex items-start gap-3">
                    {getSeverityIcon(finding.severity)}
                    <div className="flex-1">
                      <div className="flex items-center gap-2">
                        <code className="text-sm font-mono bg-gray-100 px-2 py-1 rounded">
                          {finding.file_path}
                          {finding.line_number && `:${finding.line_number}`}
                        </code>
                        <span className="text-xs uppercase px-2 py-0.5 rounded bg-gray-100 text-gray-600">
                          {finding.severity}
                        </span>
                      </div>
                      <p className="text-gray-700 mt-2">{finding.message}</p>
                      {finding.rule_id && (
                        <span className="text-xs text-gray-500 mt-1 block">
                          Rule: {finding.rule_id}
                        </span>
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
