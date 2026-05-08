import { useEffect, useState } from "react";
import { settingsApi, LLMSettings } from "../api/settings";
import { Key, Trash2, Check, Plus, Loader2 } from "lucide-react";

export default function Settings() {
  const [settings, setSettings] = useState<LLMSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [testing, setTesting] = useState<number | null>(null);
  const [showAddForm, setShowAddForm] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchSettings = async () => {
    setLoading(true);
    try {
      const data = await settingsApi.getLLMSettings();
      setSettings(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load settings");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSettings();
  }, []);

  const handleTest = async (id: number) => {
    setTesting(id);
    try {
      await settingsApi.testProvider(id);
      alert("Test successful!");
    } catch (err) {
      alert("Test failed: " + (err instanceof Error ? err.message : "Unknown error"));
    } finally {
      setTesting(null);
    }
  };

  const handleDelete = async (id: number) => {
    if (!confirm("Are you sure you want to delete this provider?")) return;
    try {
      await settingsApi.deleteProvider(id);
      await fetchSettings();
    } catch (err) {
      alert("Failed to delete: " + (err instanceof Error ? err.message : "Unknown error"));
    }
  };

  const handleSetDefault = async (id: number) => {
    try {
      await settingsApi.setDefaultProvider(id);
      await fetchSettings();
    } catch (err) {
      alert("Failed to set default: " + (err instanceof Error ? err.message : "Unknown error"));
    }
  };

  const maskKey = (key: string) => {
    if (key.length <= 8) return "••••••••";
    return key.slice(0, 4) + "••••••••" + key.slice(-4);
  };

  if (loading) {
    return (
      <div className="p-6">
        <div className="animate-pulse space-y-4">
          <div className="h-8 w-48 bg-gray-200 rounded" />
          <div className="h-32 bg-gray-200 rounded-lg" />
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900">LLM Settings</h1>
        <button
          onClick={() => setShowAddForm(!showAddForm)}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
        >
          <Plus className="w-4 h-4" />
          Add Provider
        </button>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-4 text-red-700">
          {error}
        </div>
      )}

      {showAddForm && (
        <AddProviderForm
          onCancel={() => setShowAddForm(false)}
          onSuccess={() => {
            setShowAddForm(false);
            fetchSettings();
          }}
        />
      )}

      <div className="space-y-4">
        {settings?.providers.length === 0 ? (
          <div className="bg-gray-50 border border-gray-200 rounded-lg p-8 text-center">
            <Key className="w-12 h-12 mx-auto text-gray-400 mb-4" />
            <h3 className="text-lg font-medium text-gray-900">No LLM providers configured</h3>
            <p className="text-gray-500 mt-2">Add a provider to get started with AI code reviews</p>
          </div>
        ) : (
          settings?.providers.map((provider) => (
            <div key={provider.id} className="bg-white border rounded-lg p-6">
              <div className="flex items-start justify-between">
                <div className="flex-1">
                  <div className="flex items-center gap-3">
                    <h3 className="font-semibold text-gray-900">{provider.name}</h3>
                    {provider.is_default && (
                      <span className="text-xs px-2 py-1 bg-blue-100 text-blue-700 rounded">
                        Default
                      </span>
                    )}
                    {provider.is_active && (
                      <span className="text-xs px-2 py-1 bg-green-100 text-green-700 rounded">
                        Active
                      </span>
                    )}
                  </div>
                  <div className="mt-2 space-y-1 text-sm text-gray-600">
                    <p>Provider: {provider.provider_type}</p>
                    <p>Model: {provider.model_name}</p>
                    <p className="flex items-center gap-2">
                      API Key: <code className="bg-gray-100 px-2 py-1 rounded">{maskKey(provider.api_key)}</code>
                    </p>
                    {provider.api_endpoint && (
                      <p>Endpoint: {provider.api_endpoint}</p>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => handleTest(provider.id)}
                    disabled={testing === provider.id}
                    className="px-3 py-1.5 text-sm bg-gray-100 hover:bg-gray-200 rounded-lg flex items-center gap-1.5 disabled:opacity-50"
                  >
                    {testing === provider.id ? (
                      <Loader2 className="w-3 h-3 animate-spin" />
                    ) : (
                      <Check className="w-3 h-3" />
                    )}
                    Test
                  </button>
                  {!provider.is_default && (
                    <button
                      onClick={() => handleSetDefault(provider.id)}
                      className="px-3 py-1.5 text-sm bg-gray-100 hover:bg-gray-200 rounded-lg"
                    >
                      Set Default
                    </button>
                  )}
                  <button
                    onClick={() => handleDelete(provider.id)}
                    className="px-3 py-1.5 text-sm text-red-600 hover:bg-red-50 rounded-lg"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </div>
            </div>
          ))
        )}
      </div>

      <div className="mt-8 p-4 bg-gray-50 rounded-lg">
        <h3 className="font-medium text-gray-900 mb-2">Current Model Chain</h3>
        <p className="text-sm text-gray-600">
          {settings?.default_provider
            ? `Using provider #${settings.default_provider} as default`
            : "No default provider set. Please set a default provider."}
        </p>
      </div>
    </div>
  );
}

function AddProviderForm({
  onCancel,
  onSuccess,
}: {
  onCancel: () => void;
  onSuccess: () => void;
}) {
  const [formData, setFormData] = useState({
    name: "",
    provider_type: "openai",
    api_key: "",
    model_name: "gpt-4",
    api_endpoint: "",
    is_active: true,
    is_default: false,
  });
  const [saving, setSaving] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      await settingsApi.addProvider(formData);
      onSuccess();
    } catch (err) {
      alert("Failed to add provider: " + (err instanceof Error ? err.message : "Unknown error"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="bg-white border rounded-lg p-6 mb-6">
      <h3 className="font-semibold text-gray-900 mb-4">Add LLM Provider</h3>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Name</label>
          <input
            type="text"
            required
            value={formData.name}
            onChange={(e) => setFormData({ ...formData, name: e.target.value })}
            className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            placeholder="My OpenAI Key"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Provider</label>
          <select
            value={formData.provider_type}
            onChange={(e) => setFormData({ ...formData, provider_type: e.target.value })}
            className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
          >
            <option value="openai">OpenAI</option>
            <option value="anthropic">Anthropic</option>
            <option value="google">Google</option>
            <option value="azure">Azure OpenAI</option>
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">API Key</label>
          <input
            type="password"
            required
            value={formData.api_key}
            onChange={(e) => setFormData({ ...formData, api_key: e.target.value })}
            className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            placeholder="sk-..."
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Model</label>
          <input
            type="text"
            required
            value={formData.model_name}
            onChange={(e) => setFormData({ ...formData, model_name: e.target.value })}
            className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            placeholder="gpt-4"
          />
        </div>
        <div className="md:col-span-2">
          <label className="block text-sm font-medium text-gray-700 mb-1">Endpoint (optional)</label>
          <input
            type="text"
            value={formData.api_endpoint}
            onChange={(e) => setFormData({ ...formData, api_endpoint: e.target.value })}
            className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            placeholder="https://api.openai.com/v1"
          />
        </div>
      </div>
      <div className="flex justify-end gap-3 mt-4">
        <button
          type="button"
          onClick={onCancel}
          className="px-4 py-2 text-gray-700 hover:bg-gray-100 rounded-lg"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={saving}
          className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
        >
          {saving ? "Saving..." : "Add Provider"}
        </button>
      </div>
    </form>
  );
}
