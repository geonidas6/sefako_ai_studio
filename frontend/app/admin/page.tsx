'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { api } from '../../lib/api';

interface ProviderConfig {
  provider: string;
  name: string;
  is_enabled: boolean;
  active_model: string | null;
  has_api_key: boolean;
  models: string[];
  tokens_used: number;
}

interface CostSummary {
  provider: string;
  name: string;
  tokens_used: number;
}

export default function AdminDashboard() {
  const router = useRouter();
  const [configs, setConfigs] = useState<ProviderConfig[]>([]);
  const [assignments, setAssignments] = useState<Record<string, string>>({});
  const [costs, setCosts] = useState<CostSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [successMsg, setSuccessMsg] = useState('');

  // Local form state for API keys (so we don't save until click save)
  const [apiKeys, setApiKeys] = useState<Record<string, string>>({});
  const [testingKey, setTestingKey] = useState<Record<string, boolean>>({});
  const [testResult, setTestResult] = useState<Record<string, { success: boolean; message: string }>>({});

  useEffect(() => {
    if (!api.auth.isLoggedIn()) {
      router.push('/admin/login');
      return;
    }

    async function loadAdminData() {
      try {
        const [configsData, assignmentsData, costsData] = await Promise.all([
          api.admin.getConfigs(),
          api.admin.getAssignments(),
          api.admin.getCosts(),
        ]);
        setConfigs(configsData);
        setAssignments(assignmentsData);
        setCosts(costsData);
      } catch (err: any) {
        console.error('Failed to load admin data:', err);
        setError(err.message || 'Impossible de charger les données.');
      } finally {
        setLoading(false);
      }
    }

    loadAdminData();
  }, [router]);

  const handleLogout = () => {
    api.auth.logout();
    router.push('/admin/login');
  };

  const handleUpdateProvider = async (provider: string, isEnabled: boolean, activeModel: string) => {
    setError('');
    setSuccessMsg('');
    try {
      const apiKey = apiKeys[provider] || undefined;
      await api.admin.updateConfig(provider, {
        is_enabled: isEnabled,
        active_model: activeModel,
        api_key: apiKey,
      });

      // Refresh configs & costs
      const [newConfigs, newCosts] = await Promise.all([
        api.admin.getConfigs(),
        api.admin.getCosts(),
      ]);
      setConfigs(newConfigs);
      setCosts(newCosts);

      // Clear key input after success
      if (apiKey) {
        setApiKeys({ ...apiKeys, [provider]: '' });
      }

      setSuccessMsg(`Configuration de ${provider} mise à jour avec succès.`);
      setTimeout(() => setSuccessMsg(''), 4000);
    } catch (err: any) {
      setError(err.message || 'Erreur lors de la mise à jour.');
    }
  };

  const handleTestConnection = async (provider: string, activeModel: string) => {
    const key = apiKeys[provider];
    if (!key) {
      alert('Veuillez saisir une clé API pour la tester.');
      return;
    }

    setTestingKey({ ...testingKey, [provider]: true });
    setTestResult({ ...testResult, [provider]: undefined as any });

    try {
      const res = await api.admin.testConnection(provider, key, activeModel);
      setTestResult({
        ...testResult,
        [provider]: { success: res.success, message: res.message || 'Connexion réussie !' },
      });
    } catch (err: any) {
      setTestResult({
        ...testResult,
        [provider]: { success: false, message: err.message || 'Erreur lors de la connexion.' },
      });
    } finally {
      setTestingKey({ ...testingKey, [provider]: false });
    }
  };

  const handleAssignmentChange = async (agent: string, provider: string) => {
    setError('');
    setSuccessMsg('');
    try {
      await api.admin.updateAssignment(agent, provider);
      setAssignments({ ...assignments, [agent]: provider });
      setSuccessMsg(`Agent "${agent}" assigné à "${provider}" avec succès.`);
      setTimeout(() => setSuccessMsg(''), 4000);
    } catch (err: any) {
      setError(err.message || "Erreur lors de l'affectation.");
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-[#05070f] flex items-center justify-center text-muted-foreground">
        Chargement de la console d'administration...
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#05070f] flex flex-col relative overflow-hidden">
      {/* Glows */}
      <div className="absolute top-[-20%] right-[-10%] w-[60%] h-[60%] rounded-full bg-violet-900/5 blur-[150px] pointer-events-none" />
      <div className="absolute bottom-[-20%] left-[-10%] w-[60%] h-[60%] rounded-full bg-cyan-900/5 blur-[150px] pointer-events-none" />

      {/* Header */}
      <header className="w-full border-b border-white/5 bg-[#090b14]/50 backdrop-blur-md sticky top-0 z-20">
        <div className="max-w-7xl mx-auto px-6 py-4 flex justify-between items-center">
          <div className="flex items-center gap-3">
            <Link href="/" className="text-xl font-bold bg-gradient-to-r from-violet-400 via-fuchsia-400 to-cyan-400 bg-clip-text text-transparent font-display tracking-wider">
              AIA STUDIO
            </Link>
            <span className="text-xs px-2.5 py-0.5 rounded-full border border-violet-500/30 bg-violet-950/20 text-violet-300 font-medium font-sans">
              Admin console
            </span>
          </div>
          <div className="flex items-center gap-4">
            <Link href="/" className="text-xs text-muted-foreground hover:text-white transition-colors">
              ← Retour à l'accueil
            </Link>
            <button
              onClick={handleLogout}
              className="text-xs bg-red-950/30 border border-red-500/20 hover:bg-red-900/20 text-red-400 px-3.5 py-2 rounded-lg font-medium transition-all"
            >
              Déconnexion
            </button>
          </div>
        </div>
      </header>

      {/* Container */}
      <main className="flex-1 max-w-7xl mx-auto px-6 py-10 w-full z-10 space-y-10">
        {/* Status Alerts */}
        {error && (
          <div className="p-4 rounded-xl bg-red-950/30 border border-red-500/20 text-red-400 text-sm font-medium">
            ⚠️ {error}
          </div>
        )}
        {successMsg && (
          <div className="p-4 rounded-xl bg-emerald-950/30 border border-emerald-500/20 text-emerald-400 text-sm font-medium">
            ✅ {successMsg}
          </div>
        )}

        {/* Top summary row: Agent assignments & Cost monitoring */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
          {/* Agent Assignments Card */}
          <div className="glass-panel p-6 rounded-2xl border border-white/5 lg:col-span-2">
            <h2 className="text-lg font-bold text-white mb-2 font-display">Assignation des Agents par Département</h2>
            <p className="text-muted-foreground text-xs mb-6">Associez un LLM spécifique à chaque étape du workflow multi-agents.</p>

            <div className="space-y-4">
              {[
                { key: 'strategy', name: '📈 Stratégie & Growth', desc: 'Analyse marché, modèle business et KPIs' },
                { key: 'ux', name: '🎨 Conception & UX', desc: 'Conception interfaces et parcours utilisateur' },
                { key: 'engineering', name: '⚙️ Ingénierie & Architecture', desc: 'Stack technique et modélisation MCD' },
                { key: 'devops', name: '🛡️ DevOps & Sécurité', desc: 'Infrastructures cloud et pipelines CI/CD' },
                { key: 'orchestrator', name: '🧠 Orchestrateur', desc: 'Synthèse finale, arbitrage et CDC' },
              ].map((agent) => (
                <div
                  key={agent.key}
                  className="flex flex-col sm:flex-row sm:items-center justify-between p-4 rounded-xl bg-white/5 border border-white/5 gap-3"
                >
                  <div className="min-w-0">
                    <h3 className="text-sm font-bold text-white mb-0.5">{agent.name}</h3>
                    <p className="text-xs text-muted-foreground">{agent.desc}</p>
                  </div>
                  <select
                    value={assignments[agent.key] || 'mock'}
                    onChange={(e) => handleAssignmentChange(agent.key, e.target.value)}
                    className="px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-white text-xs font-semibold focus:outline-none focus:border-violet-500"
                  >
                    <option value="mock" className="bg-[#090b14]">Mock (Simulation locale)</option>
                    {configs
                      .filter((c) => c.is_enabled)
                      .map((c) => (
                        <option key={c.provider} value={c.provider} className="bg-[#090b14]">
                          {c.name} ({c.active_model})
                        </option>
                      ))}
                  </select>
                </div>
              ))}
            </div>
          </div>

          {/* Cost Summary Card */}
          <div className="glass-panel p-6 rounded-2xl border border-white/5 flex flex-col justify-between">
            <div>
              <h2 className="text-lg font-bold text-white mb-2 font-display">Consommation des Jetons (Tokens)</h2>
              <p className="text-muted-foreground text-xs mb-6">Total accumulé des requêtes envoyées aux APIs.</p>

              <div className="space-y-4">
                {costs.length === 0 ? (
                  <p className="text-xs text-muted-foreground text-center py-6">Aucun jeton consommé pour le moment.</p>
                ) : (
                  costs.map((c) => (
                    <div key={c.provider} className="flex justify-between items-center py-2 border-b border-white/5">
                      <span className="text-xs text-muted-foreground">{c.name}</span>
                      <span className="text-sm font-semibold text-white font-mono">{c.tokens_used.toLocaleString()}</span>
                    </div>
                  ))
                )}
              </div>
            </div>

            <div className="mt-6 p-4 rounded-xl bg-violet-950/10 border border-violet-500/20 text-[11px] text-violet-300 leading-relaxed">
              💡 Les providers non configurés ou désactivés redirigent automatiquement les requêtes vers le mode <strong>Mock</strong> si les agents y font appel.
            </div>
          </div>
        </div>

        {/* LLM Configurations Details */}
        <div>
          <h2 className="text-xl font-bold text-white mb-2 font-display">Configurations des API LLM</h2>
          <p className="text-muted-foreground text-xs mb-6">Activez et gérez vos clés d'API sécurisées pour chaque grand modèle.</p>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {configs.map((config) => {
              const isEnabled = config.is_enabled;
              const activeModel = config.active_model || config.models[0] || '';
              const keyInput = apiKeys[config.provider] || '';

              return (
                <div
                  key={config.provider}
                  className={`glass-panel p-6 rounded-2xl border transition-all ${
                    isEnabled ? 'border-violet-500/20 bg-violet-950/5' : 'border-white/5'
                  }`}
                >
                  <div className="flex justify-between items-start mb-4">
                    <div>
                      <h3 className="text-base font-bold text-white flex items-center gap-2">
                        {config.name}
                        {isEnabled && <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />}
                      </h3>
                      <span className="text-xs text-muted-foreground uppercase tracking-widest font-mono">
                        {config.provider}
                      </span>
                    </div>
                    <label className="relative inline-flex items-center cursor-pointer">
                      <input
                        type="checkbox"
                        checked={isEnabled}
                        onChange={(e) => handleUpdateProvider(config.provider, e.target.checked, activeModel)}
                        className="sr-only peer"
                      />
                      <div className="w-9 h-5 bg-white/10 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-violet-600"></div>
                    </label>
                  </div>

                  <div className="space-y-4 text-xs">
                    {/* Model Selector */}
                    <div>
                      <label className="block text-muted-foreground mb-1">Modèle actif</label>
                      <select
                        value={activeModel}
                        onChange={(e) => handleUpdateProvider(config.provider, isEnabled, e.target.value)}
                        className="w-full px-3 py-2.5 rounded-lg bg-white/5 border border-white/10 text-white font-semibold focus:outline-none focus:border-violet-500"
                      >
                        {config.models.map((model) => (
                          <option key={model} value={model} className="bg-[#090b14]">
                            {model}
                          </option>
                        ))}
                      </select>
                    </div>

                    {/* API Key Input */}
                    <div>
                      <label className="block text-muted-foreground mb-1">
                        Clé API {config.has_api_key && <span className="text-emerald-400 font-medium">(Déjà enregistrée)</span>}
                      </label>
                      <div className="flex gap-2">
                        <input
                          type="password"
                          value={keyInput}
                          onChange={(e) => setApiKeys({ ...apiKeys, [config.provider]: e.target.value })}
                          className="flex-1 px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-white font-mono placeholder:text-muted-foreground/30 focus:outline-none focus:border-violet-500"
                          placeholder={config.has_api_key ? '••••••••••••••••' : 'Entrer la clé API'}
                        />
                        <button
                          type="button"
                          onClick={() => handleTestConnection(config.provider, activeModel)}
                          disabled={!keyInput || testingKey[config.provider]}
                          className="px-3 py-2 bg-white/5 border border-white/10 hover:bg-white/10 text-white font-semibold rounded-lg transition-all text-xs disabled:opacity-30 disabled:pointer-events-none"
                        >
                          {testingKey[config.provider] ? 'Test...' : 'Tester'}
                        </button>
                      </div>

                      {/* Test connection report */}
                      {testResult[config.provider] && (
                        <div
                          className={`mt-2 p-2 rounded-md font-medium text-[11px] ${
                            testResult[config.provider].success
                              ? 'bg-emerald-950/20 border border-emerald-500/20 text-emerald-400'
                              : 'bg-red-950/20 border border-red-500/20 text-red-400'
                          }`}
                        >
                          {testResult[config.provider].success ? '✓ ' : '✗ '}
                          {testResult[config.provider].message}
                        </div>
                      )}
                    </div>

                    {/* Save button if key is entered */}
                    {keyInput && (
                      <button
                        type="button"
                        onClick={() => handleUpdateProvider(config.provider, isEnabled, activeModel)}
                        className="w-full py-2 bg-violet-600 hover:bg-violet-500 text-white font-bold rounded-lg transition-all"
                      >
                        Enregistrer la clé API
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="w-full max-w-7xl mx-auto px-6 py-8 border-t border-white/5 text-xs text-muted-foreground text-center">
        © 2026 AIA Studio. Tous droits réservés.
      </footer>
    </div>
  );
}
