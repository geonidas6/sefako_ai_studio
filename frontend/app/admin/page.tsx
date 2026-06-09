'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { motion } from 'framer-motion';
import { 
  ShieldAlert, 
  CheckCircle2, 
  Settings, 
  LogOut, 
  Database, 
  Cpu, 
  TrendingUp, 
  Palette, 
  Settings2, 
  ShieldCheck,
  Brain,
  ChevronLeft,
  Key,
  BarChart3,
  Loader2,
  ExternalLink,
  Plus
} from 'lucide-react';
import { api } from '../../lib/api';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';

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

const providerKeyLinks: Record<string, string> = {
  gemini: 'https://aistudio.google.com/app/apikey',
  anthropic: 'https://console.anthropic.com/settings/keys',
  openai: 'https://platform.openai.com/api-keys',
  grok: 'https://console.x.ai/',
  mistral: 'https://console.mistral.ai/api-keys',
};

export default function AdminDashboard() {
  const router = useRouter();
  const [configs, setConfigs] = useState<ProviderConfig[]>([]);
  const [assignments, setAssignments] = useState<Record<string, string>>({});
  const [costs, setCosts] = useState<CostSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [successMsg, setSuccessMsg] = useState('');

  const [apiKeys, setApiKeys] = useState<Record<string, string>>({});
  const [newModels, setNewModels] = useState<Record<string, string>>({});
  const [addingModel, setAddingModel] = useState<Record<string, boolean>>({});
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

      const [newConfigs, newCosts] = await Promise.all([
        api.admin.getConfigs(),
        api.admin.getCosts(),
      ]);
      setConfigs(newConfigs);
      setCosts(newCosts);

      if (apiKey) setApiKeys({ ...apiKeys, [provider]: '' });
      setSuccessMsg(`Configuration de ${provider} mise à jour.`);
      setTimeout(() => setSuccessMsg(''), 4000);
    } catch (err: any) {
      setError(err.message || 'Erreur lors de la mise à jour.');
    }
  };

  const handleTestConnection = async (provider: string, activeModel: string) => {
    const key = apiKeys[provider];
    if (!key) return;
    setTestingKey({ ...testingKey, [provider]: true });
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

  const handleAddModel = async (provider: string) => {
    const model = (newModels[provider] || '').trim();
    if (!model) return;
    setError('');
    setSuccessMsg('');
    setAddingModel({ ...addingModel, [provider]: true });
    try {
      await api.admin.addModel(provider, model);
      await api.admin.updateConfig(provider, {
        is_enabled: configs.find(c => c.provider === provider)?.is_enabled || false,
        active_model: model,
      });
      const newConfigs = await api.admin.getConfigs();
      setConfigs(newConfigs);
      setNewModels({ ...newModels, [provider]: '' });
      setSuccessMsg(`Modèle "${model}" ajouté.`);
      setTimeout(() => setSuccessMsg(''), 4000);
    } catch (err: any) {
      setError(err.message || "Erreur lors de l'ajout du modèle.");
    } finally {
      setAddingModel({ ...addingModel, [provider]: false });
    }
  };

  const handleAssignmentChange = async (agent: string, provider: string) => {
    setError('');
    setSuccessMsg('');
    try {
      await api.admin.updateAssignment(agent, provider);
      setAssignments({ ...assignments, [agent]: provider });
      setSuccessMsg(`Agent "${agent}" assigné.`);
      setTimeout(() => setSuccessMsg(''), 4000);
    } catch (err: any) {
      setError(err.message || "Erreur lors de l'affectation.");
    }
  };

  if (loading) return <div className="min-h-screen flex items-center justify-center"><BarChart3 className="h-8 w-8 animate-spin text-primary" /></div>;

  return (
    <div className="max-w-7xl mx-auto px-6 py-12 md:py-20 space-y-12">
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} className="flex justify-between items-end">
        <div>
          <h1 className="text-3xl font-bold font-display tracking-tight">Console d'Administration</h1>
          <p className="text-muted-foreground mt-1">Configurez les cerveaux de votre agence multi-agents.</p>
        </div>
        <Button variant="outline" size="sm" onClick={handleLogout} className="text-destructive hover:bg-destructive/10">
          <LogOut className="mr-2 h-4 w-4" /> Déconnexion
        </Button>
      </motion.div>

      {/* Status Alerts */}
      {(error || successMsg) && (
        <div className="fixed bottom-8 right-8 z-50 animate-in space-y-2">
          {error && (
            <Card className="bg-destructive/10 border-destructive/20 text-destructive p-4 flex items-center gap-3">
              <ShieldAlert className="h-5 w-5" /> {error}
            </Card>
          )}
          {successMsg && (
            <Card className="bg-emerald-500/10 border-emerald-500/20 text-emerald-500 p-4 flex items-center gap-3">
              <CheckCircle2 className="h-5 w-5" /> {successMsg}
            </Card>
          )}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Assignments */}
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle className="text-lg flex items-center gap-2">
              <Database className="h-5 w-5 text-primary" />
              Assignation des Départements
            </CardTitle>
            <CardDescription>Associez un LLM spécifique à chaque étape du workflow.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {[
              { key: 'strategy', label: 'Stratégie', icon: TrendingUp },
              { key: 'ux', label: 'Conception UX', icon: Palette },
              { key: 'engineering', label: 'Ingénierie', icon: Settings2 },
              { key: 'devops', label: 'DevOps', icon: ShieldCheck },
              { key: 'orchestrator', label: 'Orchestrateur', icon: Brain },
            ].map((agent) => (
              <div key={agent.key} className="flex flex-col sm:flex-row sm:items-center justify-between p-4 rounded-xl bg-muted/30 border border-border/50 gap-4">
                <div className="flex items-center gap-3">
                  <div className="p-2 rounded-lg bg-background border border-border">
                    <agent.icon className="h-4 w-4 text-muted-foreground" />
                  </div>
                  <span className="text-sm font-bold">{agent.label}</span>
                </div>
                <select
                  value={assignments[agent.key] || 'mock'}
                  onChange={(e) => handleAssignmentChange(agent.key, e.target.value)}
                  className="px-3 py-2 rounded-lg bg-background border border-border text-xs font-semibold focus:outline-none focus:ring-1 focus:ring-primary"
                >
                  <option value="mock">Mock Simulator</option>
                  {configs.filter(c => c.is_enabled).map(c => (
                    <option key={c.provider} value={c.provider}>{c.name} ({c.active_model})</option>
                  ))}
                </select>
              </div>
            ))}
          </CardContent>
        </Card>

        {/* Costs */}
        <Card>
          <CardHeader>
            <CardTitle className="text-lg flex items-center gap-2">
              <BarChart3 className="h-5 w-5 text-primary" />
              Monitoring
            </CardTitle>
            <CardDescription>Utilisation des tokens par fournisseur.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="space-y-3">
              {costs.map((c) => (
                <div key={c.provider} className="flex justify-between items-center py-2 border-b border-border/50">
                  <span className="text-xs text-muted-foreground">{c.name}</span>
                  <span className="text-sm font-bold font-mono">{c.tokens_used.toLocaleString()}</span>
                </div>
              ))}
              {costs.length === 0 && <p className="text-xs text-center text-muted-foreground py-10 italic">Aucune donnée.</p>}
            </div>
            <div className="p-4 rounded-lg bg-primary/5 border border-primary/10 text-[10px] text-muted-foreground leading-relaxed">
              <span className="font-bold text-primary block mb-1">💡 INFO</span>
              Les requêtes sont redirigées vers le mode <strong>Mock</strong> si le fournisseur assigné est désactivé ou non configuré.
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Provider Configs */}
      <div className="space-y-6">
        <h2 className="text-xl font-bold font-display tracking-tight flex items-center gap-2">
          <Key className="h-5 w-5 text-primary" /> Configurateurs LLM
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {configs.map((config) => {
            const isEnabled = config.is_enabled;
            const activeModel = config.active_model || config.models[0] || '';
            const keyInput = apiKeys[config.provider] || '';
            const test = testResult[config.provider];
            const keyLink = providerKeyLinks[config.provider];

            return (
              <Card key={config.provider} className={cn("transition-all", isEnabled ? "border-primary/30 shadow-lg shadow-primary/5" : "border-border/60")}>
                <CardHeader className="flex flex-row items-start justify-between gap-4 pb-4">
                  <div>
                    <CardTitle className="text-base">{config.name}</CardTitle>
                    <CardDescription className="font-mono text-[10px] uppercase">{config.provider}</CardDescription>
                  </div>
                  <div className="flex items-center gap-3">
                    {keyLink && (
                      <Button asChild variant="outline" size="sm" className="h-8 px-3 text-xs">
                        <a href={keyLink} target="_blank" rel="noreferrer" title={`Ouvrir la console ${config.name}`}>
                          Obtenir une clé
                          <ExternalLink className="ml-2 h-3 w-3" />
                        </a>
                      </Button>
                    )}
                    <label className="relative inline-flex items-center cursor-pointer">
                      <input
                        type="checkbox"
                        checked={isEnabled}
                        onChange={(e) => handleUpdateProvider(config.provider, e.target.checked, activeModel)}
                        className="sr-only peer"
                      />
                      <div className="w-9 h-5 bg-muted rounded-full peer peer-checked:bg-primary after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:after:translate-x-full" />
                    </label>
                  </div>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold text-muted-foreground uppercase">Modèle</label>
                    <select
                      value={activeModel}
                      onChange={(e) => handleUpdateProvider(config.provider, isEnabled, e.target.value)}
                      className="w-full px-3 py-2 rounded-lg bg-muted/50 border border-border text-xs font-semibold focus:outline-none focus:ring-1 focus:ring-primary"
                    >
                      {config.models.map(m => <option key={m} value={m}>{m}</option>)}
                    </select>
                    <div className="flex gap-2 pt-2">
                      <Input
                        value={newModels[config.provider] || ''}
                        onChange={(e) => setNewModels({ ...newModels, [config.provider]: e.target.value })}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') {
                            e.preventDefault();
                            handleAddModel(config.provider);
                          }
                        }}
                        placeholder="Nouveau modèle, ex: grok-4"
                        className="h-9 font-mono text-xs"
                        maxLength={64}
                      />
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={!(newModels[config.provider] || '').trim() || addingModel[config.provider]}
                        onClick={() => handleAddModel(config.provider)}
                        className="h-9 shrink-0"
                      >
                        {addingModel[config.provider] ? <Loader2 className="h-3 w-3 animate-spin" /> : <Plus className="h-3 w-3" />}
                        <span className="ml-2 hidden sm:inline">Ajouter</span>
                      </Button>
                    </div>
                  </div>

                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold text-muted-foreground uppercase flex items-center justify-between">
                      Clé API
                      {config.has_api_key && <span className="text-emerald-500 font-bold lowercase italic tracking-normal">Enregistrée ✓</span>}
                    </label>
                    <div className="flex gap-2">
                      <Input
                        type="password"
                        value={keyInput}
                        onChange={(e) => setApiKeys({ ...apiKeys, [config.provider]: e.target.value })}
                        placeholder={config.has_api_key ? '••••••••••••' : 'Ajouter une clé'}
                        className="h-9 font-mono"
                      />
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={!keyInput || testingKey[config.provider]}
                        onClick={() => handleTestConnection(config.provider, activeModel)}
                        className="h-9"
                      >
                        {testingKey[config.provider] ? <Loader2 className="h-3 w-3 animate-spin" /> : 'Test'}
                      </Button>
                    </div>
                  </div>

                  {test && (
                    <div className={cn("p-2 rounded-lg text-[10px] font-medium border", test.success ? "bg-emerald-500/5 border-emerald-500/20 text-emerald-500" : "bg-destructive/5 border-destructive/20 text-destructive")}>
                      {test.success ? '✓' : '✗'} {test.message}
                    </div>
                  )}

                  {keyInput && (
                    <Button
                      onClick={() => handleUpdateProvider(config.provider, isEnabled, activeModel)}
                      className="w-full h-9"
                    >
                      Enregistrer la clé
                    </Button>
                  )}
                </CardContent>
              </Card>
            );
          })}
        </div>
      </div>
    </div>
  );
}
