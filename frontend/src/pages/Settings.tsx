import { useEffect, useState } from "react";
import { settingsApi, LLMProvider } from "../api/settings";
import { Key, Trash2, Check, Plus, Loader2, X, AlertTriangle, Zap, ChevronDown } from "lucide-react";

export default function Settings() {
  const [providers, setProviders] = useState<LLMProvider[]>([]);
  const [loading, setLoading] = useState(true);
  const [testing, setTesting] = useState<number | null>(null);
  const [showAddForm, setShowAddForm] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchProviders = async () => {
    setLoading(true);
    try {
      const data = await settingsApi.getLLMSettings();
      setProviders(data);
    } catch {
      setError("Failed to load LLM providers");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchProviders(); }, []);

  const handleTest = async (provider: LLMProvider) => {
    setTesting(provider.id);
    try {
      const result = await settingsApi.testProvider({
        provider: provider.provider,
        model_name: provider.model_name,
        api_key: provider.masked_key,
        base_url: provider.base_url || undefined,
      });
      alert(result.message || "Test successful!");
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { message?: string } } })?.response?.data?.message || "Test failed";
      alert(msg);
    } finally {
      setTesting(null);
    }
  };

  const handleDelete = async (id: number) => {
    if (!confirm("Delete this provider?")) return;
    try {
      await settingsApi.deleteProvider(id);
      setProviders((p) => p.filter((x) => x.id !== id));
    } catch {
      alert("Failed to delete provider");
    }
  };

  const handleSetDefault = async (id: number) => {
    try {
      await settingsApi.setDefaultProvider(id);
      setProviders((p) =>
        p.map((x) => ({ ...x, priority: x.id === id ? 0 : x.priority }))
      );
    } catch {
      alert("Failed to set default provider");
    }
  };

  const defaultProvider = providers.find((p) => p.priority === 0);

  if (loading) {
    return (
      <div className="min-h-[60vh] flex flex-col items-center justify-center space-y-4">
        <Loader2 className="w-10 h-10 animate-spin" style={{ color: "var(--accent)" }} />
        <p className="animate-pulse" style={{ color: "var(--text-secondary)" }}>Loading settings...</p>
      </div>
    );
  }

  return (
    <div className="space-y-8 animate-fade-in">
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-4">
        <div>
          <h1 className="text-4xl font-bold mb-2 text-gradient">LLM Settings</h1>
          <p className="text-lg" style={{ color: "var(--text-secondary)" }}>
            Manage your AI model providers and API keys.
          </p>
        </div>
        <button onClick={() => setShowAddForm(!showAddForm)} className="btn-primary flex items-center gap-2">
          <Plus className="w-4 h-4" />
          Add Provider
        </button>
      </div>

      {error && (
        <div className="glass-card p-4 flex items-center gap-3" style={{ border: "1px solid rgba(239,68,68,0.2)", backgroundColor: "rgba(239,68,68,0.05)" }}>
          <AlertTriangle className="w-5 h-5 flex-shrink-0" style={{ color: "var(--error)" }} />
          <p className="text-sm" style={{ color: "var(--error)" }}>{error}</p>
        </div>
      )}

      {showAddForm && (
        <AddProviderForm
          onCancel={() => setShowAddForm(false)}
          onSuccess={() => { setShowAddForm(false); fetchProviders(); }}
        />
      )}

      {providers.length === 0 ? (
        <div className="glass-card p-12 text-center flex flex-col items-center justify-center space-y-4">
          <div className="w-16 h-16 rounded-2xl flex items-center justify-center border" style={{ backgroundColor: "var(--bg-tertiary)", borderColor: "var(--border)" }}>
            <Key className="w-8 h-8" style={{ color: "var(--text-muted)" }} />
          </div>
          <h3 className="text-xl font-semibold" style={{ color: "var(--text-primary)" }}>No LLM providers configured</h3>
          <p className="max-w-md" style={{ color: "var(--text-secondary)" }}>
            Add your API keys to enable AI-powered code reviews. We support OpenAI, Anthropic, Google, and custom endpoints.
          </p>
          <button onClick={() => setShowAddForm(true)} className="btn-primary mt-2">
            <Plus className="w-4 h-4" /> Add Your First Provider
          </button>
        </div>
      ) : (
        <div className="space-y-4">
          {providers.map((provider) => (
            <div key={provider.id} className="glass-card p-6">
              <div className="flex flex-col md:flex-row md:items-start justify-between gap-4">
                <div className="flex items-start gap-4">
                  <div className="w-12 h-12 rounded-xl flex items-center justify-center border" style={{ backgroundColor: "var(--bg-tertiary)", borderColor: "var(--border)" }}>
                    <Zap className="w-6 h-6" style={{ color: "var(--accent)" }} />
                  </div>
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <h3 className="text-lg font-bold" style={{ color: "var(--text-primary)" }}>
                        {provider.name || provider.provider}
                      </h3>
                      <span className="badge badge-info uppercase text-[10px]">{provider.provider}</span>
                      {provider.priority === 0 && <span className="badge badge-success">Default</span>}
                    </div>
                    <div className="flex flex-wrap items-center gap-4 text-sm" style={{ color: "var(--text-secondary)" }}>
                      <span>Model: <code className="text-[var(--accent)]">{provider.model_name}</code></span>
                      {provider.base_url && (
                        <span>Endpoint: <code className="text-xs" style={{ color: "var(--text-muted)" }}>{provider.base_url}</code></span>
                      )}
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-2 flex-shrink-0">
                  <button onClick={() => handleTest(provider)} disabled={testing === provider.id} className="btn-secondary flex items-center gap-1.5 text-xs">
                    {testing === provider.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <Check className="w-3 h-3" />}
                    Test
                  </button>
                  {provider.priority !== 0 && (
                    <button onClick={() => handleSetDefault(provider.id)} className="btn-secondary text-xs">Set Default</button>
                  )}
                  <button onClick={() => handleDelete(provider.id)} className="btn-secondary flex items-center gap-1.5 text-xs" style={{ color: "var(--error)", borderColor: "rgba(239,68,68,0.2)" }}>
                    <Trash2 className="w-3 h-3" />
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {defaultProvider && (
        <div className="glass-card p-6" style={{ border: "1px solid rgba(16,185,129,0.2)", backgroundColor: "rgba(16,185,129,0.05)" }}>
          <div className="flex items-center gap-2 mb-2">
            <Check className="w-5 h-5" style={{ color: "var(--success)" }} />
            <h3 className="font-bold" style={{ color: "var(--success)" }}>Active Model Chain</h3>
          </div>
          <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
            Using <code className="font-semibold" style={{ color: "var(--success)" }}>{defaultProvider.name || defaultProvider.provider}</code> ({defaultProvider.model_name}) as the default provider.
          </p>
        </div>
      )}
    </div>
  );
}

function AddProviderForm({ onCancel, onSuccess }: { onCancel: () => void; onSuccess: () => void }) {
  const [formData, setFormData] = useState({
    name: "", provider: "openai", api_key: "", model_name: "gpt-4o", base_url: "", is_active: true,
  });
  const [saving, setSaving] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null);
  const [testingKey, setTestingKey] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      await settingsApi.addProvider(formData);
      onSuccess();
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { provider?: string[] } } })?.response?.data?.provider?.[0] || "Failed to add provider";
      alert(msg);
    } finally {
      setSaving(false);
    }
  };

  const handleTestKey = async () => {
    setTestingKey(true);
    setTestResult(null);
    try {
      const result = await settingsApi.testProvider({
        provider: formData.provider,
        model_name: formData.model_name,
        api_key: formData.api_key,
        base_url: formData.base_url || undefined,
      });
      setTestResult({ ok: true, message: result.message || "API key is valid!" });
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { message?: string } } })?.response?.data?.message || "Invalid API key";
      setTestResult({ ok: false, message: msg });
    } finally {
      setTestingKey(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="glass-card p-6 space-y-6">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-bold" style={{ color: "var(--text-primary)" }}>Add LLM Provider</h3>
        <button type="button" onClick={onCancel} className="btn-ghost p-2">
          <X className="w-4 h-4" />
        </button>
      </div>

      {testResult && (
        <div className="p-3 rounded-lg border text-sm" style={testResult.ok
          ? { borderColor: "rgba(16,185,129,0.2)", backgroundColor: "rgba(16,185,129,0.05)", color: "var(--success)" }
          : { borderColor: "rgba(239,68,68,0.2)", backgroundColor: "rgba(239,68,68,0.05)", color: "var(--error)" }}>
          {testResult.message}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium mb-1" style={{ color: "var(--text-secondary)" }}>Name</label>
          <input type="text" required value={formData.name} onChange={(e) => setFormData({ ...formData, name: e.target.value })} className="input-field" placeholder="My OpenAI Key" />
        </div>
        <div>
          <label className="block text-sm font-medium mb-1" style={{ color: "var(--text-secondary)" }}>Provider</label>
          <div className="relative">
            <select value={formData.provider} onChange={(e) => setFormData({ ...formData, provider: e.target.value })} className="input-field appearance-none pr-10">
              <option value="openai">OpenAI</option>
              <option value="anthropic">Anthropic</option>
              <option value="google_vertex">Google Vertex</option>
              <option value="mistral">Mistral</option>
              <option value="custom">Custom (OpenAI-compatible)</option>
            </select>
            <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 pointer-events-none" style={{ color: "var(--text-muted)" }} />
          </div>
        </div>
        <div>
          <label className="block text-sm font-medium mb-1" style={{ color: "var(--text-secondary)" }}>Model</label>
          <input type="text" required value={formData.model_name} onChange={(e) => setFormData({ ...formData, model_name: e.target.value })} className="input-field" placeholder="gpt-4o" />
        </div>
        <div>
          <label className="block text-sm font-medium mb-1" style={{ color: "var(--text-secondary)" }}>API Key</label>
          <div className="flex gap-2">
            <input type="password" required value={formData.api_key} onChange={(e) => setFormData({ ...formData, api_key: e.target.value })} className="input-field flex-1" placeholder="sk-..." />
            <button type="button" onClick={handleTestKey} disabled={!formData.api_key || testingKey} className="btn-secondary whitespace-nowrap">
              {testingKey ? <Loader2 className="w-4 h-4 animate-spin" /> : "Test Key"}
            </button>
          </div>
        </div>
        <div className="md:col-span-2">
          <label className="block text-sm font-medium mb-1" style={{ color: "var(--text-secondary)" }}>Endpoint (optional)</label>
          <input type="url" value={formData.base_url} onChange={(e) => setFormData({ ...formData, base_url: e.target.value })} className="input-field" placeholder="https://api.openai.com/v1" />
        </div>
      </div>

      <div className="flex justify-end gap-3">
        <button type="button" onClick={onCancel} className="btn-secondary">Cancel</button>
        <button type="submit" disabled={saving} className="btn-primary">
          {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : "Add Provider"}
        </button>
      </div>
    </form>
  );
}
