'use client';

import { useState, useEffect } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
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
  GitBranch,
  Sparkles,
  Link2,
  RefreshCw,
  Plus,
  Users,
  Trash2,
  Save,
  FolderKanban,
  Search,
  Calendar
} from 'lucide-react';
import { api } from '../../lib/api';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';

type AdminSection = 'projects' | 'departments' | 'settings' | 'git' | 'security';

interface Project {
  id: string;
  title: string;
  input_text: string;
  status: string;
  created_at: string;
  completed_at?: string | null;
}

interface ProviderConfig {
  provider: string;
  name: string;
  is_enabled: boolean;
  active_model: string | null;
  has_api_key: boolean;
  models: string[];
  tokens_used: number;
  requests_per_minute: number;
}

interface CostSummary {
  provider: string;
  name: string;
  tokens_used: number;
}

interface EmployeeConfig {
  id?: string;
  name: string;
  role: string;
  avatar: string;
  briefing: string;
  sort_order: number;
  is_enabled: boolean;
}

interface DepartmentConfig {
  id?: string;
  key: string;
  label: string;
  description: string;
  mission: string;
  sort_order: number;
  is_enabled: boolean;
  employees: EmployeeConfig[];
}

interface WorkflowSettings {
  debate_rounds: number;
  max_debate_rounds: number;
  llm_timeout_seconds: number;
  min_timeout_seconds: number;
  max_timeout_seconds: number;
  final_json_retry_count: number;
  min_final_json_retry_count: number;
  max_final_json_retry_count: number;
}

interface GenerationSettings {
  root_path: string;
  require_technical_approval: boolean;
}

interface GitConnection {
  provider: string;
  username: string | null;
  email: string | null;
  connected: boolean;
  has_token: boolean;
  default_branch: string;
  is_enabled: boolean;
}

interface GitSettings {
  connection: GitConnection;
  github_oauth_client_id?: string | null;
  has_github_oauth_client_secret?: boolean;
  github_oauth_source?: string;
  commit_message_provider?: string;
  commit_message_model?: string;
  commit_message_source?: string;
}

interface QwenAuthStatus {
  authenticated: boolean;
  method: string;
  config_dir?: string;
}

const providerKeyLinks: Record<string, string> = {
  gemini: 'https://aistudio.google.com/app/apikey',
  deepseek: 'https://api-docs.deepseek.com/',
  anthropic: 'https://console.anthropic.com/settings/keys',
  openai: 'https://platform.openai.com/api-keys',
  openrouter: 'https://openrouter.ai/docs/quickstart',
  nvidia: 'https://build.nvidia.com/',
  grok: 'https://console.x.ai/',
  groq: 'https://console.groq.com/keys',
  mistral: 'https://console.mistral.ai/api-keys',
  qwen: 'https://dashscope.console.aliyun.com/apiKey',
  azure_openai: 'https://portal.azure.com/',
  bedrock: 'https://console.aws.amazon.com/bedrock/',
};

const providerSetupNotes: Record<string, string> = {
  deepseek: 'Compatible OpenAI endpoint. Utilise une clé DeepSeek classique.',
  azure_openai: 'Nécessite AZURE_OPENAI_ENDPOINT et AZURE_OPENAI_API_VERSION côté backend.',
  bedrock: 'Utilise les identifiants AWS du backend et la variable BEDROCK_REGION.',
};

export default function AdminDashboard() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [activeSection, setActiveSection] = useState<AdminSection>('projects');
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectQuery, setProjectQuery] = useState('');
  const [configs, setConfigs] = useState<ProviderConfig[]>([]);
  const [assignments, setAssignments] = useState<Record<string, string>>({});
  const [departments, setDepartments] = useState<DepartmentConfig[]>([]);
  const [savingDepartments, setSavingDepartments] = useState(false);
  const [costs, setCosts] = useState<CostSummary[]>([]);
  const [workflowSettings, setWorkflowSettings] = useState<WorkflowSettings>({ debate_rounds: 1, max_debate_rounds: 3, llm_timeout_seconds: 180, min_timeout_seconds: 30, max_timeout_seconds: 900, final_json_retry_count: 2, min_final_json_retry_count: 0, max_final_json_retry_count: 5 });
  const [savingWorkflowSettings, setSavingWorkflowSettings] = useState(false);
  const [generationSettings, setGenerationSettings] = useState<GenerationSettings>({ root_path: '/opt', require_technical_approval: true });
  const [savingGenerationSettings, setSavingGenerationSettings] = useState(false);
  const [gitSettings, setGitSettings] = useState<GitSettings>({
    connection: {
      provider: 'github',
      username: '',
      email: '',
      connected: false,
      has_token: false,
      default_branch: 'main',
      is_enabled: false,
    },
    github_oauth_client_id: '',
    has_github_oauth_client_secret: false,
    github_oauth_source: 'environment',
    commit_message_provider: 'gemini',
    commit_message_model: '',
    commit_message_source: 'default',
  });
  const [githubOAuthForm, setGithubOAuthForm] = useState({
    client_id: '',
    client_secret: '',
    has_client_secret: false,
    source: 'environment',
  });
  const [startingGitHubAuth, setStartingGitHubAuth] = useState(false);
  const [disconnectingGitHub, setDisconnectingGitHub] = useState(false);
  const [qwenAuth, setQwenAuth] = useState<QwenAuthStatus>({ authenticated: false, method: 'none' });
  const [startingQwenAuth, setStartingQwenAuth] = useState(false);
  const [savingQwenCliKey, setSavingQwenCliKey] = useState(false);
  const [passwordForm, setPasswordForm] = useState({
    currentPassword: '',
    newPassword: '',
    confirmPassword: '',
  });
  const [savingPasswordChange, setSavingPasswordChange] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [successMsg, setSuccessMsg] = useState('');

  const [apiKeys, setApiKeys] = useState<Record<string, string>>({});
  const [rateLimits, setRateLimits] = useState<Record<string, string>>({});
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
      const results = await Promise.allSettled([
        api.projects.list(),
        api.admin.getConfigs(),
        api.admin.getAssignments(),
        api.admin.getDepartments(),
        api.admin.getCosts(),
        api.admin.getWorkflowSettings(),
        api.admin.getGenerationSettings(),
        api.admin.getGitSettings(),
        api.admin.getQwenAuthStatus(),
      ]);

      const [projectsData, configsData, assignmentsData, departmentsData, costsData, workflowSettingsData, generationSettingsData, gitSettingsData, qwenAuthData] = results;

      const failures = results.filter((item): item is PromiseRejectedResult => item.status === 'rejected');
      const githubRedirectStatus = searchParams.get('github');
      const authFailure = failures.find((item) => String(item.reason?.message || '').toLowerCase().includes('identifiants invalides'));

      if (authFailure) {
        api.auth.logout();
        router.push('/admin/login');
        setLoading(false);
        return;
      }

      if (projectsData.status === 'fulfilled') setProjects(projectsData.value);
      if (configsData.status === 'fulfilled') setConfigs(configsData.value);
      if (assignmentsData.status === 'fulfilled') setAssignments(assignmentsData.value);
      if (departmentsData.status === 'fulfilled') setDepartments(departmentsData.value);
      if (costsData.status === 'fulfilled') setCosts(costsData.value);
      if (workflowSettingsData.status === 'fulfilled') setWorkflowSettings(workflowSettingsData.value);
      if (generationSettingsData.status === 'fulfilled') setGenerationSettings(generationSettingsData.value);
      if (gitSettingsData.status === 'fulfilled') {
        const commitProvider = gitSettingsData.value.commit_message_provider || 'gemini';
        const providerConfig = configsData.status === 'fulfilled'
          ? configsData.value.find((config: ProviderConfig) => config.provider === commitProvider)
            || configsData.value.find((config: ProviderConfig) => config.provider !== 'mock')
          : null;
        setGitSettings({
          ...gitSettingsData.value,
          commit_message_provider: commitProvider,
          commit_message_model: gitSettingsData.value.commit_message_model || providerConfig?.models?.[0] || '',
          commit_message_source: gitSettingsData.value.commit_message_source || 'default',
        });
        setGithubOAuthForm({
          client_id: gitSettingsData.value.github_oauth_client_id || '',
          client_secret: '',
          has_client_secret: Boolean(gitSettingsData.value.has_github_oauth_client_secret),
          source: gitSettingsData.value.github_oauth_source || 'environment',
        });
      }
      if (qwenAuthData.status === 'fulfilled') setQwenAuth(qwenAuthData.value);

      if (githubRedirectStatus === 'connected') {
        setSuccessMsg('GitHub connecté avec succès.');
        setTimeout(() => setSuccessMsg(''), 5000);
        window.history.replaceState({}, '', '/admin');
      } else if (failures.length > 0) {
        const firstMessage = String(failures[0].reason?.message || "Certaines données admin n'ont pas pu être chargées.");
        setError(`Chargement partiel : ${firstMessage}`);
      }

      setLoading(false);
    }
    loadAdminData();
  }, [router, searchParams]);

  useEffect(() => {
    const handleAuthExpired = () => {
      api.auth.logout();
      router.push('/admin/login');
    };

    window.addEventListener('aia-auth-expired', handleAuthExpired as EventListener);
    return () => window.removeEventListener('aia-auth-expired', handleAuthExpired as EventListener);
  }, [router]);

  const handleLogout = () => {
    api.auth.logout();
    router.push('/admin/login');
  };

  const filteredProjects = projects.filter((project) => {
    const query = projectQuery.trim().toLowerCase();
    if (!query) return true;
    return project.title.toLowerCase().includes(query) || project.input_text.toLowerCase().includes(query);
  });

  const projectCounts = projects.reduce<Record<string, number>>((acc, project) => {
    acc[project.status] = (acc[project.status] || 0) + 1;
    return acc;
  }, {});

  const handleDeleteProject = async (project: Project) => {
    if (!confirm(`Supprimer le projet "${project.title}" ?`)) return;
    setError('');
    setSuccessMsg('');
    try {
      await api.projects.delete(project.id);
      setProjects((current) => current.filter((item) => item.id !== project.id));
      setSuccessMsg('Projet supprimé.');
      setTimeout(() => setSuccessMsg(''), 4000);
    } catch (err: any) {
      setError(err.message || 'Erreur lors de la suppression du projet.');
    }
  };

  const handleUpdateProvider = async (provider: string, isEnabled: boolean, activeModel: string) => {
    setError('');
    setSuccessMsg('');
    try {
      const apiKey = apiKeys[provider] || undefined;
      const configuredRpm = rateLimits[provider];
      const parsedRpm = configuredRpm ? Number.parseInt(configuredRpm, 10) : undefined;
      await api.admin.updateConfig(provider, {
        is_enabled: isEnabled,
        active_model: activeModel,
        api_key: apiKey,
        requests_per_minute: Number.isFinite(parsedRpm) ? parsedRpm : undefined,
      });

      const [newConfigs, newCosts] = await Promise.all([
        api.admin.getConfigs(),
        api.admin.getCosts(),
      ]);
      setConfigs(newConfigs);
      setCosts(newCosts);
      setRateLimits({
        ...rateLimits,
        [provider]: String(newConfigs.find((config: ProviderConfig) => config.provider === provider)?.requests_per_minute || ''),
      });

      if (apiKey) setApiKeys({ ...apiKeys, [provider]: '' });
      setSuccessMsg(`Configuration de ${provider} mise à jour.`);
      setTimeout(() => setSuccessMsg(''), 4000);
    } catch (err: any) {
      setError(err.message || 'Erreur lors de la mise à jour.');
    }
  };

  const handleTestConnection = async (provider: string, activeModel: string) => {
    const key = apiKeys[provider];
    if (provider !== 'bedrock' && !key) return;
    setTestingKey({ ...testingKey, [provider]: true });
    try {
      const res = await api.admin.testConnection(provider, key || '', activeModel);
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

    // Client-side validation: check if the provider is valid
    const validProviders = configs.map(c => c.provider);
    if (provider !== 'mock' && !validProviders.includes(provider)) {
      setError(`Fournisseur LLM inconnu ou invalide: "${provider}". Veuillez sélectionner un fournisseur valide.`);
      return;
    }

    try {
      await api.admin.updateAssignment(agent, provider);
      setAssignments({ ...assignments, [agent]: provider });
      setSuccessMsg(`Agent "${agent}" assigné.`);
      setTimeout(() => setSuccessMsg(''), 4000);
    } catch (err: any) {
      setError(err.message || "Erreur lors de l'affectation.");
    }
  };

  const updateDepartment = (key: string, patch: Partial<DepartmentConfig>) => {
    setDepartments((current) => current.map((department) => (
      department.key === key ? { ...department, ...patch } : department
    )));
  };

  const updateEmployee = (departmentKey: string, index: number, patch: Partial<EmployeeConfig>) => {
    setDepartments((current) => current.map((department) => {
      if (department.key !== departmentKey) return department;
      return {
        ...department,
        employees: department.employees.map((employee, employeeIndex) => (
          employeeIndex === index ? { ...employee, ...patch } : employee
        )),
      };
    }));
  };

  const addEmployee = (departmentKey: string) => {
    setDepartments((current) => current.map((department) => {
      if (department.key !== departmentKey) return department;
      const nextIndex = department.employees.length + 1;
      return {
        ...department,
        employees: [
          ...department.employees,
          {
            name: 'Nouvel employé',
            role: 'Spécialiste IA',
            avatar: 'IA',
            briefing: 'Décris ici sa responsabilité dans le département.',
            sort_order: nextIndex * 10,
            is_enabled: true,
          },
        ],
      };
    }));
  };

  const removeEmployee = (departmentKey: string, index: number) => {
    setDepartments((current) => current.map((department) => {
      if (department.key !== departmentKey) return department;
      return {
        ...department,
        employees: department.employees.filter((_, employeeIndex) => employeeIndex !== index),
      };
    }));
  };

  const handleSaveDepartments = async () => {
    setError('');
    setSuccessMsg('');
    setSavingDepartments(true);
    try {
      const response = await api.admin.updateDepartments(departments);
      setDepartments(response.departments);
      setSuccessMsg('Départements et employés enregistrés.');
      setTimeout(() => setSuccessMsg(''), 4000);
    } catch (err: any) {
      setError(err.message || 'Erreur lors de la sauvegarde des départements.');
    } finally {
      setSavingDepartments(false);
    }
  };

  const refreshQwenAuth = async () => {
    try {
      const status = await api.admin.getQwenAuthStatus();
      setQwenAuth(status);
      return status;
    } catch {
      return null;
    }
  };

  const handleStartQwenAuth = async () => {
    setError('');
    setSuccessMsg('');
    setStartingQwenAuth(true);
    try {
      const response = await api.admin.startQwenAuth();
      if (response.url) {
        window.open(response.url, '_blank', 'noopener,noreferrer');
        setSuccessMsg('Lien Qwen ouvert. Termine l’autorisation puis clique sur Rafraîchir le statut.');
        setTimeout(() => setSuccessMsg(''), 6000);
      }
    } catch (err: any) {
      setError(err.message || 'Impossible de démarrer l’authentification Qwen.');
    } finally {
      setStartingQwenAuth(false);
    }
  };

  const handleSaveQwenCliKey = async () => {
    const key = apiKeys.qwen || '';
    if (!key.trim()) return;
    setError('');
    setSuccessMsg('');
    setSavingQwenCliKey(true);
    try {
      await api.admin.saveQwenCliApiKey(key);
      await refreshQwenAuth();
      setSuccessMsg('Clé Qwen sauvegardée aussi pour le CLI.');
      setTimeout(() => setSuccessMsg(''), 5000);
    } catch (err: any) {
      setError(err.message || 'Impossible de sauvegarder la clé Qwen pour le CLI.');
    } finally {
      setSavingQwenCliKey(false);
    }
  };

  const handleSaveWorkflowSettings = async () => {
    setError('');
    setSuccessMsg('');
    setSavingWorkflowSettings(true);
    try {
      const response = await api.admin.updateWorkflowSettings({
        debate_rounds: workflowSettings.debate_rounds,
        llm_timeout_seconds: workflowSettings.llm_timeout_seconds,
        final_json_retry_count: workflowSettings.final_json_retry_count,
      });
      setWorkflowSettings(response);
      setSuccessMsg('Paramètres du workflow enregistrés.');
      setTimeout(() => setSuccessMsg(''), 4000);
    } catch (err: any) {
      setError(err.message || 'Erreur lors de la sauvegarde du workflow.');
    } finally {
      setSavingWorkflowSettings(false);
    }
  };

  const handleSaveGenerationSettings = async () => {
    setError('');
    setSuccessMsg('');
    setSavingGenerationSettings(true);
    try {
      const response = await api.admin.updateGenerationSettings(generationSettings);
      setGenerationSettings(response);
      setSuccessMsg('Paramètres de génération enregistrés.');
      setTimeout(() => setSuccessMsg(''), 4000);
    } catch (err: any) {
      setError(err.message || 'Erreur lors de la sauvegarde des paramètres de génération.');
    } finally {
      setSavingGenerationSettings(false);
    }
  };

  const handleStartGitHubAuth = async () => {
    setError('');
    setSuccessMsg('');
    setStartingGitHubAuth(true);
    try {
      const response = await api.admin.startGitHubOAuth();
      if (response.url) {
        window.location.href = response.url;
        setSuccessMsg('Redirection vers GitHub en cours. Termine l’autorisation puis reviens sur cette page.');
        setTimeout(() => setSuccessMsg(''), 6000);
      }
    } catch (err: any) {
      const message = String(err?.message || '');
      if (message.includes('client_id GitHub OAuth') || message.includes('configuration GitHub OAuth est incomplète')) {
        setError("GitHub OAuth n’est pas encore configuré sur le serveur. Ajoute `GITHUB_OAUTH_CLIENT_ID` et `GITHUB_OAUTH_CLIENT_SECRET` dans l’environnement du backend, puis redémarre l’application. Callback attendu : `https://api-sefako-ai-studio.it-sefako.com/api/admin/github/oauth/callback`.");
      } else {
        setError(err.message || 'Impossible de démarrer l’autorisation GitHub.');
      }
    } finally {
      setStartingGitHubAuth(false);
    }
  };

  const handleSaveGitHubOAuthConfig = async () => {
    setError('');
    setSuccessMsg('');
    const clientId = githubOAuthForm.client_id.trim();
    const clientSecret = githubOAuthForm.client_secret.trim();
    if (!clientId) {
      setError('Le client_id GitHub OAuth est requis.');
      return;
    }
    if (!githubOAuthForm.has_client_secret && !clientSecret) {
      setError('Le client secret GitHub OAuth est requis au moins une fois.');
      return;
    }

    try {
      const response = await api.admin.updateGitHubOAuthConfig({
        client_id: clientId,
        client_secret: clientSecret || null,
      });
      await refreshGitHubState();
      setGitSettings((current) => ({
        ...current,
        github_oauth_client_id: clientId,
        has_github_oauth_client_secret: response.has_client_secret || Boolean(clientSecret),
        github_oauth_source: response.source || 'database',
      }));
      setGithubOAuthForm((current) => ({
        ...current,
        client_secret: '',
        has_client_secret: response.has_client_secret || Boolean(clientSecret),
        source: response.source || 'database',
      }));
      setSuccessMsg('Configuration GitHub OAuth enregistrée.');
      setTimeout(() => setSuccessMsg(''), 4000);
    } catch (err: any) {
      setError(err.message || 'Impossible de sauvegarder la configuration GitHub OAuth.');
    }
  };

  const refreshGitHubState = async () => {
    try {
      const [status, settings] = await Promise.allSettled([
        api.admin.getGitHubStatus(),
        api.admin.getGitSettings(),
      ]);
      if (status.status === 'fulfilled') setGitSettings((current) => ({
        ...current,
        connection: { ...current.connection, ...status.value },
      }));
      if (settings.status === 'fulfilled') {
        setGitSettings((current) => ({
          ...current,
          ...settings.value,
        }));
        setGithubOAuthForm({
          client_id: settings.value.github_oauth_client_id || '',
          client_secret: '',
          has_client_secret: Boolean(settings.value.has_github_oauth_client_secret),
          source: settings.value.github_oauth_source || 'environment',
        });
      }
    } catch {
      // ignore
    }
  };

  const handleDisconnectGitHub = async () => {
    setError('');
    setSuccessMsg('');
    setDisconnectingGitHub(true);
    try {
      const response = await api.admin.disconnectGitHub();
      setGitSettings((current) => ({
        ...current,
        connection: {
          ...current.connection,
          ...response,
          connected: false,
          has_token: false,
          is_enabled: false,
        },
      }));
      setSuccessMsg('Compte GitHub déconnecté.');
      setTimeout(() => setSuccessMsg(''), 4000);
    } catch (err: any) {
      setError(err.message || 'Impossible de déconnecter GitHub.');
    } finally {
      setDisconnectingGitHub(false);
    }
  };

  const handleSaveGitSettings = async () => {
    setError('');
    setSuccessMsg('');
    try {
      const response = await api.admin.updateGitSettings({
        default_branch: gitSettings.connection.default_branch,
        is_enabled: gitSettings.connection.is_enabled,
      });
      setGitSettings((current) => ({
        ...current,
        connection: {
          ...current.connection,
          ...response,
        },
      }));
      setSuccessMsg('Préférences GitHub enregistrées.');
      setTimeout(() => setSuccessMsg(''), 4000);
    } catch (err: any) {
      setError(err.message || 'Erreur lors de la sauvegarde GitHub.');
    }
  };

  const handleSaveCommitMessageSettings = async () => {
    setError('');
    setSuccessMsg('');
    const provider = (gitSettings.commit_message_provider || '').trim();
    const model = (gitSettings.commit_message_model || '').trim();
    if (!provider) {
      setError('Le provider du message de commit est requis.');
      return;
    }
    if (!model) {
      setError('Le modèle du message de commit est requis.');
      return;
    }
    try {
      const response = await api.admin.updateCommitMessageSettings({ provider, model });
      setGitSettings((current) => ({
        ...current,
        commit_message_provider: response.provider,
        commit_message_model: response.model,
        commit_message_source: response.source,
      }));
      setSuccessMsg('Configuration du message de commit enregistrée.');
      setTimeout(() => setSuccessMsg(''), 4000);
    } catch (err: any) {
      setError(err.message || 'Erreur lors de la sauvegarde de la configuration du message de commit.');
    }
  };

  const handleChangePassword = async () => {
    setError('');
    setSuccessMsg('');

    if (!passwordForm.currentPassword || !passwordForm.newPassword || !passwordForm.confirmPassword) {
      setError('Merci de remplir les trois champs.');
      return;
    }

    setSavingPasswordChange(true);
    try {
      await api.auth.changePassword(
        passwordForm.currentPassword,
        passwordForm.newPassword,
        passwordForm.confirmPassword
      );
      setPasswordForm({ currentPassword: '', newPassword: '', confirmPassword: '' });
      setSuccessMsg('Mot de passe mis à jour. Reconnexion en cours...');
      setTimeout(() => {
        api.auth.logout();
        router.push('/admin/login');
      }, 1400);
    } catch (err: any) {
      setError(err.message || 'Erreur lors du changement de mot de passe.');
    } finally {
      setSavingPasswordChange(false);
    }
  };

  const adminSections = [
    {
      key: 'projects' as const,
      label: 'Projet',
      description: 'Suivi et accès aux analyses',
      icon: FolderKanban,
    },
    {
      key: 'departments' as const,
      label: 'Départements & employés',
      description: 'Organisation des équipes IA',
      icon: Users,
    },
    {
      key: 'settings' as const,
      label: 'Paramètre',
      description: 'Providers, modèles et quotas',
      icon: Settings,
    },
    {
      key: 'git' as const,
      label: 'Git',
      description: 'Connexion et dépôts cibles',
      icon: GitBranch,
    },
    {
      key: 'security' as const,
      label: 'Sécurité',
      description: 'Mot de passe de l’admin',
      icon: Key,
    },
  ];

  const statusLabels: Record<string, string> = {
    pending: 'En attente',
    running: 'En cours',
    paused: 'En pause',
    completed: 'Terminé',
    failed: 'Échoué',
  };

  const statusClasses: Record<string, string> = {
    pending: 'bg-muted text-muted-foreground border-border',
    running: 'bg-primary/10 text-primary border-primary/20',
    paused: 'bg-amber-500/10 text-amber-500 border-amber-500/20',
    completed: 'bg-emerald-500/10 text-emerald-500 border-emerald-500/20',
    failed: 'bg-destructive/10 text-destructive border-destructive/20',
  };

  const renderProjectsPanel = () => (
    <div className="space-y-6">
      <div className="flex flex-col lg:flex-row lg:items-end justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold font-display tracking-tight">Projet</h2>
          <p className="text-sm text-muted-foreground mt-1">Gestion rapide des projets créés dans le studio.</p>
        </div>
        <Button asChild className="h-10">
          <Link href="/studio"><Plus className="mr-2 h-4 w-4" /> Nouveau projet</Link>
        </Button>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          { label: 'Total', value: projects.length, className: 'text-foreground' },
          { label: 'En cours', value: projectCounts.running || 0, className: 'text-primary' },
          { label: 'En pause', value: projectCounts.paused || 0, className: 'text-amber-500' },
          { label: 'Terminés', value: projectCounts.completed || 0, className: 'text-emerald-500' },
        ].map((item) => (
          <Card key={item.label} className="bg-muted/20 border-border/60">
            <CardContent className="p-4">
              <p className="text-[10px] text-muted-foreground font-bold uppercase tracking-widest">{item.label}</p>
              <p className={cn('text-2xl font-bold font-display mt-2', item.className)}>{item.value}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      <Card className="border-border/60">
        <CardContent className="p-4">
          <div className="relative max-w-xl">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              value={projectQuery}
              onChange={(event) => setProjectQuery(event.target.value)}
              placeholder="Rechercher un projet..."
              className="pl-9 h-10"
            />
          </div>
        </CardContent>
      </Card>

      <div className="space-y-3">
        {filteredProjects.length === 0 ? (
          <Card className="border-dashed bg-muted/20 p-10 text-center">
            <p className="font-semibold">Aucun projet trouvé</p>
            <p className="text-sm text-muted-foreground mt-1">Créez un projet ou ajustez la recherche.</p>
          </Card>
        ) : filteredProjects.map((project) => (
          <Card key={project.id} className="border-border/60 hover:border-primary/30 transition-colors">
            <CardContent className="p-4 flex flex-col lg:flex-row lg:items-center justify-between gap-4">
              <div className="min-w-0 space-y-2">
                <div className="flex flex-wrap items-center gap-2">
                  <span className={cn('text-[10px] uppercase font-bold tracking-widest px-2 py-0.5 rounded-full border', statusClasses[project.status] || statusClasses.pending)}>
                    {statusLabels[project.status] || project.status}
                  </span>
                  <span className="text-[10px] text-muted-foreground inline-flex items-center gap-1">
                    <Calendar className="h-3 w-3" /> {new Date(project.created_at).toLocaleDateString('fr-FR')}
                  </span>
                </div>
                <div>
                  <h3 className="font-bold truncate">{project.title}</h3>
                  <p className="text-sm text-muted-foreground line-clamp-2">{project.input_text}</p>
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <Button asChild variant="outline" size="sm">
                  <Link href={`/projects/${project.id}`}>Ouvrir</Link>
                </Button>
                <Button variant="ghost" size="icon" onClick={() => handleDeleteProject(project)} className="text-muted-foreground hover:text-destructive">
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );

  const renderDepartmentsPanel = () => (
      <div className="space-y-6">
        <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-4">
          <div>
            <h2 className="text-2xl font-bold font-display tracking-tight flex items-center gap-2">
              <Users className="h-5 w-5 text-primary" /> Départements & employés
            </h2>
            <p className="text-sm text-muted-foreground mt-1">
              Configurez les équipes visibles pendant l'analyse. Le workflow actuel utilise ces 5 départements fixes.
            </p>
          </div>
          <Button onClick={handleSaveDepartments} disabled={savingDepartments} className="shrink-0">
            {savingDepartments ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Save className="mr-2 h-4 w-4" />}
            Sauvegarder les équipes
          </Button>
        </div>

        <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
          {departments.length === 0 ? (
            <Card className="border-dashed border-border/60 bg-muted/20 xl:col-span-2">
              <CardContent className="p-10 text-center">
                <p className="font-semibold">Aucun département chargé</p>
                <p className="mt-1 text-sm text-muted-foreground">Le backend n'a renvoyé aucun employé ou le chargement a été partiel. Recharge la page après correction.</p>
              </CardContent>
            </Card>
          ) : departments.map((department) => (
            <Card key={department.key} className={cn("border-border/70", department.is_enabled ? "" : "opacity-70")}>
              <CardHeader className="space-y-4">
                <div className="flex items-start justify-between gap-4">
                  <div className="space-y-1 flex-1">
                    <CardDescription className="font-mono text-[10px] uppercase">{department.key}</CardDescription>
                    <Input
                      value={department.label}
                      onChange={(e) => updateDepartment(department.key, { label: e.target.value })}
                      className="h-10 text-base font-bold"
                    />
                  </div>
                  <label className="relative inline-flex items-center cursor-pointer mt-6">
                    <input
                      type="checkbox"
                      checked={department.is_enabled}
                      onChange={(e) => updateDepartment(department.key, { is_enabled: e.target.checked })}
                      className="sr-only peer"
                    />
                    <div className="w-9 h-5 bg-muted rounded-full peer peer-checked:bg-primary after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:after:translate-x-full" />
                  </label>
                </div>
                <div className="space-y-2">
                  <label className="text-[10px] font-bold text-muted-foreground uppercase">Mission du département</label>
                  <textarea
                    value={department.mission}
                    onChange={(e) => updateDepartment(department.key, { mission: e.target.value })}
                    rows={3}
                    className="w-full rounded-lg bg-muted/40 border border-border px-3 py-2 text-xs leading-relaxed focus:outline-none focus:ring-1 focus:ring-primary resize-none"
                  />
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-bold">Employés</h3>
                  <Button variant="outline" size="sm" onClick={() => addEmployee(department.key)} className="h-8 text-xs">
                    <Plus className="mr-2 h-3 w-3" /> Ajouter
                  </Button>
                </div>

                <div className="space-y-3">
                  {department.employees.map((employee, index) => (
                    <div key={`${department.key}-${index}`} className="rounded-xl border border-border/70 bg-muted/20 p-4 space-y-3">
                      <div className="grid grid-cols-1 md:grid-cols-[80px_1fr_1fr_auto] gap-3 items-center">
                        <Input
                          value={employee.avatar}
                          onChange={(e) => updateEmployee(department.key, index, { avatar: e.target.value.toUpperCase().slice(0, 4) })}
                          className="h-9 text-center font-mono text-xs"
                          maxLength={4}
                        />
                        <Input
                          value={employee.name}
                          onChange={(e) => updateEmployee(department.key, index, { name: e.target.value })}
                          placeholder="Nom"
                          className="h-9 text-xs"
                        />
                        <Input
                          value={employee.role}
                          onChange={(e) => updateEmployee(department.key, index, { role: e.target.value })}
                          placeholder="Rôle"
                          className="h-9 text-xs"
                        />
                        <div className="flex items-center gap-2">
                          <label className="relative inline-flex items-center cursor-pointer">
                            <input
                              type="checkbox"
                              checked={employee.is_enabled}
                              onChange={(e) => updateEmployee(department.key, index, { is_enabled: e.target.checked })}
                              className="sr-only peer"
                            />
                            <div className="w-8 h-4 bg-muted rounded-full peer peer-checked:bg-primary after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-3 after:w-3 after:transition-all peer-checked:after:translate-x-4" />
                          </label>
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => removeEmployee(department.key, index)}
                            className="h-8 w-8 text-muted-foreground hover:text-destructive"
                            disabled={department.employees.length <= 1}
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                      </div>
                      <textarea
                        value={employee.briefing}
                        onChange={(e) => updateEmployee(department.key, index, { briefing: e.target.value })}
                        rows={2}
                        placeholder="Briefing/personnalité de cet employé pendant les discussions"
                        className="w-full rounded-lg bg-background/70 border border-border px-3 py-2 text-xs leading-relaxed focus:outline-none focus:ring-1 focus:ring-primary resize-none"
                      />
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
  );

  const renderSettingsPanel = () => (
    <div className="space-y-8">
      <div>
        <h2 className="text-2xl font-bold font-display tracking-tight">Paramètre</h2>
        <p className="text-sm text-muted-foreground mt-1">Providers IA, modèles, quotas et assignation des départements.</p>
      </div>

      <Card className="border-primary/20 bg-primary/5">
        <CardHeader>
          <CardTitle className="text-lg flex items-center gap-2">
            <FolderKanban className="h-5 w-5 text-primary" />
            Génération applicative
          </CardTitle>
          <CardDescription>Prépare la future phase de conception technique dans un workspace strictement confiné au dossier du projet.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_240px] gap-4">
            <div className="space-y-2">
              <p className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">Dossier racine de génération</p>
              <Input
                value={generationSettings.root_path}
                onChange={(event) => setGenerationSettings({ ...generationSettings, root_path: event.target.value })}
                placeholder="/opt"
                className="h-11 font-mono"
              />
              <p className="text-xs text-muted-foreground">Le backend forcera la génération dans <code>/opt</code> ou un sous-dossier de <code>/opt</code>. Aucun accès à docker_manager, Traefik ou aux autres projets ne sera autorisé.</p>
            </div>
            <div className="rounded-xl border border-border/60 bg-background/50 p-4">
              <p className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">Validation admin</p>
              <label className="mt-3 flex items-start gap-3 text-sm">
                <input
                  type="checkbox"
                  checked={generationSettings.require_technical_approval}
                  onChange={(event) => setGenerationSettings({ ...generationSettings, require_technical_approval: event.target.checked })}
                  className="mt-1 h-4 w-4 rounded border-border bg-background"
                />
                <span className="text-muted-foreground">Demander à l'admin s'il faut continuer lorsqu'on arrive à la phase conception technique.</span>
              </label>
            </div>
          </div>

          <div className="rounded-xl border border-border/60 bg-background/40 p-4 text-xs text-muted-foreground leading-relaxed">
            Nommage prévu : <code>{`{slug}_{project_id}`}</code>. Exemple : <code>/opt/todolist_0185d095-8373-4f4d-bfda-ef4fffa03239</code>. Les manifestes Docker, <code>.env.example</code> et les YAML Traefik seront générés uniquement dans ce dossier projet.
          </div>

          <div className="flex justify-end">
            <Button onClick={handleSaveGenerationSettings} disabled={savingGenerationSettings} className="h-10">
              {savingGenerationSettings ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Save className="mr-2 h-4 w-4" />}
              Enregistrer la génération
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card className="border-primary/20 bg-primary/5">
        <CardHeader>
          <CardTitle className="text-lg flex items-center gap-2">
            <Settings className="h-5 w-5 text-primary" />
            Workflow d'analyse
          </CardTitle>
          <CardDescription>Structure complète du cycle de travail des employés IA.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-5 gap-4">
            <div className="rounded-xl border border-border/60 bg-background/60 p-4">
              <p className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">Rounds d'analyse initiale</p>
              <p className="mt-3 text-3xl font-bold font-display">1</p>
              <p className="mt-2 text-xs text-muted-foreground">Fixe : chaque département produit sa première analyse.</p>
            </div>

            <div className="rounded-xl border border-primary/30 bg-primary/10 p-4">
              <p className="text-[10px] font-bold uppercase tracking-widest text-primary">Rounds de critique/débat</p>
              <div className="mt-3 flex items-center gap-3">
                <Input
                  type="number"
                  min={0}
                  max={workflowSettings.max_debate_rounds || 3}
                  value={workflowSettings.debate_rounds}
                  onChange={(event) => {
                    const parsed = Number.parseInt(event.target.value, 10);
                    const safe = Number.isFinite(parsed) ? Math.max(0, Math.min(parsed, workflowSettings.max_debate_rounds || 3)) : 0;
                    setWorkflowSettings({ ...workflowSettings, debate_rounds: safe });
                  }}
                  className="h-11 max-w-28 font-mono text-lg font-bold"
                />
                <span className="text-xs text-muted-foreground">0 à {workflowSettings.max_debate_rounds || 3}</span>
              </div>
              <p className="mt-2 text-xs text-muted-foreground">Configurable : les équipes se challengent avant l'arbitrage.</p>
            </div>

            <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-4">
              <p className="text-[10px] font-bold uppercase tracking-widest text-amber-500">Timeout LLM</p>
              <div className="mt-3 flex items-center gap-3">
                <Input
                  type="number"
                  min={workflowSettings.min_timeout_seconds || 30}
                  max={workflowSettings.max_timeout_seconds || 900}
                  value={workflowSettings.llm_timeout_seconds}
                  onChange={(event) => {
                    const parsed = Number.parseInt(event.target.value, 10);
                    const safe = Number.isFinite(parsed) ? Math.max(workflowSettings.min_timeout_seconds || 30, Math.min(parsed, workflowSettings.max_timeout_seconds || 900)) : 180;
                    setWorkflowSettings({ ...workflowSettings, llm_timeout_seconds: safe });
                  }}
                  className="h-11 max-w-32 font-mono text-lg font-bold"
                />
                <span className="text-xs text-muted-foreground">sec</span>
              </div>
              <p className="mt-2 text-xs text-muted-foreground">Durée maximale d'un appel IA avant coupure automatique et erreur récupérable.</p>
            </div>

            <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-4">
              <p className="text-[10px] font-bold uppercase tracking-widest text-destructive">Relances auto JSON</p>
              <div className="mt-3 flex items-center gap-3">
                <Input
                  type="number"
                  min={workflowSettings.min_final_json_retry_count || 0}
                  max={workflowSettings.max_final_json_retry_count || 5}
                  value={workflowSettings.final_json_retry_count}
                  onChange={(event) => {
                    const parsed = Number.parseInt(event.target.value, 10);
                    const safe = Number.isFinite(parsed) ? Math.max(workflowSettings.min_final_json_retry_count || 0, Math.min(parsed, workflowSettings.max_final_json_retry_count || 5)) : 2;
                    setWorkflowSettings({ ...workflowSettings, final_json_retry_count: safe });
                  }}
                  className="h-11 max-w-28 font-mono text-lg font-bold"
                />
                <span className="text-xs text-muted-foreground">tentatives</span>
              </div>
              <p className="mt-2 text-xs text-muted-foreground">Si la synthèse finale revient avec un JSON cassé, l'orchestrateur relance automatiquement cette étape.</p>
            </div>

            <div className="rounded-xl border border-border/60 bg-background/60 p-4">
              <p className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">Synthèse finale</p>
              <p className="mt-3 text-3xl font-bold font-display">1</p>
              <p className="mt-2 text-xs text-muted-foreground">Fixe : l'orchestrateur produit les livrables finaux.</p>
            </div>
          </div>

          <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4 rounded-xl border border-border/60 bg-background/40 p-4">
            <p className="text-xs text-muted-foreground leading-relaxed max-w-3xl">
              Recommandation actuelle : 0 à 1 round de débat pour limiter les coûts et éviter les boucles, avec un timeout LLM entre 120 et 240 secondes selon la qualité du provider. Les checkpoints permettent de reprendre sans tout régénérer.
            </p>
            <Button onClick={handleSaveWorkflowSettings} disabled={savingWorkflowSettings} className="h-10 shrink-0">
              {savingWorkflowSettings ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Save className="mr-2 h-4 w-4" />}
              Enregistrer
            </Button>
          </div>
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
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
              <span className="font-bold text-primary block mb-1">INFO</span>
              Les requêtes utilisent strictement le provider assigné. En cas d'erreur API ou de limite, l'analyse s'arrête et affiche l'erreur au projet.
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="space-y-6">
        <h3 className="text-xl font-bold font-display tracking-tight flex items-center gap-2">
          <Key className="h-5 w-5 text-primary" /> Configurateurs LLM
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
          {configs.length === 0 ? (
            <Card className="border-dashed border-border/60 bg-muted/20 md:col-span-2 xl:col-span-3">
              <CardContent className="p-10 text-center">
                <p className="font-semibold">Aucun provider chargé</p>
                <p className="mt-1 text-sm text-muted-foreground">Les configurateurs LLM n'ont pas été récupérés. Le panneau reste visible et le reste des paramètres continue de fonctionner.</p>
              </CardContent>
            </Card>
          ) : configs.map((config) => {
            const isEnabled = config.is_enabled;
            const activeModel = config.active_model || config.models[0] || '';
            const keyInput = apiKeys[config.provider] || '';
            const rpmInput = rateLimits[config.provider] ?? String(config.requests_per_minute || 1);
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
                    <label className="text-[10px] font-bold text-muted-foreground uppercase">Requêtes par minute</label>
                    <Input
                      type="number"
                      min={1}
                      max={600}
                      value={rpmInput}
                      onChange={(e) => setRateLimits({ ...rateLimits, [config.provider]: e.target.value })}
                      onBlur={() => handleUpdateProvider(config.provider, isEnabled, activeModel)}
                      className="h-9 font-mono text-xs"
                    />
                    <p className="text-[10px] text-muted-foreground">
                      Limite locale appliquée avant chaque appel à ce provider. Groq est par défaut à 2 req/min pour réduire les erreurs 429.
                    </p>
                  </div>

                  {providerSetupNotes[config.provider] && (
                    <div className="rounded-lg border border-dashed border-border/60 bg-muted/20 px-3 py-2 text-[10px] leading-relaxed text-muted-foreground">
                      {providerSetupNotes[config.provider]}
                    </div>
                  )}

                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold text-muted-foreground uppercase flex items-center justify-between">
                      Clé API {config.provider === 'bedrock' ? '(optionnelle)' : ''}
                      {config.has_api_key && <span className="text-emerald-500 font-bold lowercase italic tracking-normal">Enregistrée ✓</span>}
                    </label>
                    <div className="flex gap-2">
                      <Input
                        type="password"
                        value={keyInput}
                        onChange={(e) => setApiKeys({ ...apiKeys, [config.provider]: e.target.value })}
                        placeholder={config.provider === 'bedrock' ? 'Aucune clé requise' : (config.has_api_key ? '••••••••••••' : 'Ajouter une clé')}
                        className="h-9 font-mono"
                      />
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={(config.provider !== 'bedrock' && !keyInput) || testingKey[config.provider]}
                        onClick={() => handleTestConnection(config.provider, activeModel)}
                        className="h-9"
                      >
                        {testingKey[config.provider] ? <Loader2 className="h-3 w-3 animate-spin" /> : 'Test'}
                      </Button>
                    </div>
                  </div>

                  {config.provider === 'qwen' && (
                    <div className="rounded-xl border border-primary/20 bg-primary/5 p-3 space-y-3">
                      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                        <div>
                          <p className="text-[10px] font-bold uppercase text-primary">CLI Web Auth</p>
                          <p className="text-[10px] text-muted-foreground">Statut : {qwenAuth.authenticated ? `connecté (${qwenAuth.method})` : 'non connecté'}</p>
                          <p className="mt-1 text-[10px] text-muted-foreground leading-relaxed">L’OAuth Qwen peut être indisponible selon la version du CLI. La méthode fiable reste la clé API DashScope.</p>
                        </div>
                        <div className="flex flex-wrap gap-2">
                          <Button variant="outline" size="sm" onClick={handleStartQwenAuth} disabled={startingQwenAuth} className="h-8 text-xs">
                            {startingQwenAuth ? <Loader2 className="mr-2 h-3 w-3 animate-spin" /> : <ExternalLink className="mr-2 h-3 w-3" />}
                            Tenter Auth web
                          </Button>
                          <Button variant="ghost" size="sm" onClick={refreshQwenAuth} className="h-8 text-xs">
                            Rafraîchir
                          </Button>
                        </div>
                      </div>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={handleSaveQwenCliKey}
                        disabled={!keyInput || savingQwenCliKey}
                        className="h-8 text-xs w-full"
                      >
                        {savingQwenCliKey ? <Loader2 className="mr-2 h-3 w-3 animate-spin" /> : <Save className="mr-2 h-3 w-3" />}
                        Utiliser cette clé aussi pour le CLI Qwen
                      </Button>
                    </div>
                  )}

                  {test && (
                    <div className={cn("p-2 rounded-lg text-[10px] font-medium border", test.success ? "bg-emerald-500/5 border-emerald-500/20 text-emerald-500" : "bg-destructive/5 border-destructive/20 text-destructive")}>
                      {test.success ? '✓' : '✗'} {test.message}
                    </div>
                  )}

                  {(keyInput || config.provider === 'bedrock') && (
                    <Button
                      onClick={() => handleUpdateProvider(config.provider, isEnabled, activeModel)}
                      className="w-full h-9"
                    >
                      {config.provider === 'bedrock' ? 'Enregistrer la configuration' : 'Enregistrer la clé'}
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

  const renderGitPanel = () => {
    const commitProviderConfig = configs.find((config) => config.provider === gitSettings.commit_message_provider)
      || configs.find((config) => config.provider !== 'mock')
      || configs[0];
    const commitProviderModels = commitProviderConfig?.models || [];

    return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold font-display tracking-tight flex items-center gap-2">
          <GitBranch className="h-5 w-5 text-primary" /> GitHub Integration
        </h2>
        <p className="text-sm text-muted-foreground mt-1">
          Connecte ton compte GitHub une seule fois, puis importe ou crée les repos que les projets pourront pousser.
        </p>
      </div>

      <Card className="border-border/60">
        <CardHeader>
          <CardTitle className="text-lg flex items-center gap-2">
            <Key className="h-5 w-5 text-primary" />
            Configuration OAuth GitHub
          </CardTitle>
          <CardDescription>
            Renseigne ici le client_id et le client_secret de l’application OAuth GitHub. La valeur du secret reste masquée après enregistrement.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <div className="space-y-2">
              <label className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">Client ID</label>
              <Input
                value={githubOAuthForm.client_id}
                onChange={(event) => setGithubOAuthForm((current) => ({ ...current, client_id: event.target.value }))}
                placeholder="Ov23..."
                className="h-11 font-mono"
              />
            </div>
            <div className="space-y-2">
              <label className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">Client secret</label>
              <Input
                value={githubOAuthForm.client_secret}
                onChange={(event) => setGithubOAuthForm((current) => ({ ...current, client_secret: event.target.value }))}
                placeholder={githubOAuthForm.has_client_secret ? 'Secret déjà enregistré - laisse vide pour conserver' : 'Complète le secret OAuth'}
                type="password"
                className="h-11 font-mono"
              />
            </div>
          </div>
          <div className="flex flex-col gap-2 rounded-xl border border-border/60 bg-background/50 p-4 text-xs text-muted-foreground md:flex-row md:items-center md:justify-between">
            <span>
              Source actuelle : <strong className="text-foreground">{githubOAuthForm.source}</strong>
            </span>
            <span>
              Secret enregistré : <strong className="text-foreground">{githubOAuthForm.has_client_secret ? 'oui' : 'non'}</strong>
            </span>
          </div>
          <div className="flex justify-end">
            <Button onClick={handleSaveGitHubOAuthConfig} className="h-10">
              <Save className="mr-2 h-4 w-4" />
              Enregistrer OAuth
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card className="border-border/60">
        <CardHeader>
          <CardTitle className="text-lg flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-primary" />
            Message de commit IA
          </CardTitle>
          <CardDescription>
            Choisis quel provider et quel modèle doivent générer le message de commit avant le push Git.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <div className="space-y-2">
              <label className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">Provider</label>
              <select
                value={gitSettings.commit_message_provider || 'gemini'}
                onChange={(event) => {
                  const provider = event.target.value;
                  const providerConfig = configs.find((config) => config.provider === provider) || configs.find((config) => config.provider !== 'mock');
                  const nextModel = providerConfig?.models?.[0] || '';
                  setGitSettings((current) => ({
                    ...current,
                    commit_message_provider: provider,
                    commit_message_model: nextModel,
                  }));
                }}
                className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm"
              >
                {configs.filter((config) => config.provider !== 'mock').map((config) => (
                  <option key={config.provider} value={config.provider}>
                    {config.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-2">
              <label className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">Modèle</label>
              <select
                value={gitSettings.commit_message_model || ''}
                onChange={(event) => setGitSettings((current) => ({
                  ...current,
                  commit_message_model: event.target.value,
                }))}
                className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm"
              >
                {commitProviderModels.length === 0 ? (
                  <option value="">Aucun modèle</option>
                ) : (
                  commitProviderModels.map((model) => (
                    <option key={model} value={model}>
                      {model}
                    </option>
                  ))
                )}
              </select>
            </div>
          </div>
          <div className="flex flex-col gap-2 rounded-xl border border-border/60 bg-background/50 p-4 text-xs text-muted-foreground md:flex-row md:items-center md:justify-between">
            <span>
              Source actuelle : <strong className="text-foreground">{gitSettings.commit_message_source || 'default'}</strong>
            </span>
            <span>
              Valeur: <strong className="text-foreground">{gitSettings.commit_message_provider || 'gemini'} / {gitSettings.commit_message_model || 'auto'}</strong>
            </span>
          </div>
          <div className="flex justify-end">
            <Button onClick={handleSaveCommitMessageSettings} className="h-10">
              <Save className="mr-2 h-4 w-4" />
              Enregistrer le commit IA
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card className="border-primary/20 bg-primary/5">
        <CardHeader>
          <CardTitle className="text-lg flex items-center gap-2">
            <GitBranch className="h-5 w-5 text-primary" />
            Authorization GitHub
          </CardTitle>
          <CardDescription>
            L’admin se connecte via OAuth GitHub. Aucun token à copier-coller.
          </CardDescription>
        </CardHeader>
          <CardContent className="space-y-4">
          <div className="rounded-xl border border-amber-500/20 bg-amber-500/10 p-4 text-sm text-amber-200">
            <p className="font-semibold text-amber-100">Configuration requise</p>
            <p className="mt-1 text-xs leading-relaxed text-amber-100/80">
              Le bouton GitHub OAuth fonctionne seulement si le backend a <code>GITHUB_OAUTH_CLIENT_ID</code> et <code>GITHUB_OAUTH_CLIENT_SECRET</code> configurés. Sans ça, la connexion est bloquée côté serveur.
            </p>
          </div>

          <div className="rounded-xl border border-border/60 bg-background/60 p-4 flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
            <div className="space-y-1">
              <p className="text-sm font-semibold">
                {gitSettings.connection.connected
                  ? `Connecté${gitSettings.connection.username ? ` · ${gitSettings.connection.username}` : ''}`
                  : 'GitHub non connecté'}
              </p>
              <p className="text-xs text-muted-foreground">
                {gitSettings.connection.email || 'Aucun email détecté'} · branche par défaut {gitSettings.connection.default_branch || 'main'}
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button onClick={handleStartGitHubAuth} disabled={startingGitHubAuth} className="h-10">
                {startingGitHubAuth ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <GitBranch className="mr-2 h-4 w-4" />}
                Connect GitHub
              </Button>
              <Button variant="outline" onClick={handleDisconnectGitHub} disabled={disconnectingGitHub || !gitSettings.connection.connected} className="h-10">
                {disconnectingGitHub ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-2 h-4 w-4" />}
                Déconnecter
              </Button>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-[minmax(0,1fr)_220px] gap-4">
            <div className="space-y-2">
              <label className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">Branche par défaut</label>
              <Input
                value={gitSettings.connection.default_branch}
                onChange={(event) => setGitSettings((current) => ({
                  ...current,
                  connection: { ...current.connection, default_branch: event.target.value },
                }))}
                placeholder="main"
                className="h-11 font-mono"
              />
            </div>
            <label className="flex items-start gap-3 rounded-xl border border-border/60 bg-background/50 p-4 text-sm">
              <input
                type="checkbox"
                checked={gitSettings.connection.is_enabled}
                onChange={(event) => setGitSettings((current) => ({
                  ...current,
                  connection: { ...current.connection, is_enabled: event.target.checked },
                }))}
                className="mt-1 h-4 w-4 rounded border-border bg-background"
              />
              <span className="text-muted-foreground">
                Autoriser les pushes depuis l’app.
              </span>
            </label>
          </div>

          <div className="flex justify-end">
            <Button onClick={handleSaveGitSettings} disabled={startingGitHubAuth} className="h-10">
              <Save className="mr-2 h-4 w-4" />
              Enregistrer les préférences
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card className="border-border/60">
        <CardHeader>
          <CardTitle className="text-lg flex items-center gap-2">
            <GitBranch className="h-5 w-5 text-primary" />
            GitHub Summary
          </CardTitle>
          <CardDescription>
            Connexion GitHub active pour les pushes depuis les projets. Les options d'import de repos ont été retirées du panel admin.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="rounded-xl border border-border/60 bg-background/60 p-4 text-sm text-muted-foreground">
            Les dépôts cibles sont gérés côté projet via la liste GitHub déjà liée au compte connecté.
          </div>
        </CardContent>
      </Card>
    </div>
    );
  };

  const renderSecurityPanel = () => (
    <div className="space-y-6 max-w-3xl">
      <div>
        <h2 className="text-2xl font-bold font-display tracking-tight">Sécurité</h2>
        <p className="text-sm text-muted-foreground mt-1">
          Changez le mot de passe du compte admin actuellement connecté.
        </p>
      </div>

      <Card className="border-primary/20 bg-primary/5">
        <CardHeader>
          <CardTitle className="text-lg flex items-center gap-2">
            <Key className="h-5 w-5 text-primary" />
            Changer le mot de passe
          </CardTitle>
          <CardDescription>
            Le nouveau mot de passe doit comporter au moins 8 caractères et être confirmé.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="grid grid-cols-1 gap-4">
            <div className="space-y-2">
              <label className="text-[10px] font-bold text-muted-foreground uppercase" htmlFor="current-password">
                Mot de passe actuel
              </label>
              <Input
                id="current-password"
                type="password"
                value={passwordForm.currentPassword}
                onChange={(event) => setPasswordForm({ ...passwordForm, currentPassword: event.target.value })}
                placeholder="Mot de passe actuel"
                autoComplete="current-password"
              />
            </div>

            <div className="space-y-2">
              <label className="text-[10px] font-bold text-muted-foreground uppercase" htmlFor="new-password">
                Nouveau mot de passe
              </label>
              <Input
                id="new-password"
                type="password"
                value={passwordForm.newPassword}
                onChange={(event) => setPasswordForm({ ...passwordForm, newPassword: event.target.value })}
                placeholder="Au moins 8 caractères"
                autoComplete="new-password"
              />
            </div>

            <div className="space-y-2">
              <label className="text-[10px] font-bold text-muted-foreground uppercase" htmlFor="confirm-password">
                Confirmer le nouveau mot de passe
              </label>
              <Input
                id="confirm-password"
                type="password"
                value={passwordForm.confirmPassword}
                onChange={(event) => setPasswordForm({ ...passwordForm, confirmPassword: event.target.value })}
                placeholder="Répétez le nouveau mot de passe"
                autoComplete="new-password"
              />
            </div>
          </div>

          <div className="rounded-xl border border-border/60 bg-background/40 p-4 text-xs text-muted-foreground leading-relaxed">
            Après validation, le panneau vous déconnectera pour forcer une reconnexion avec le nouveau mot de passe.
          </div>

          <div className="flex justify-end">
            <Button onClick={handleChangePassword} disabled={savingPasswordChange} className="h-10">
              {savingPasswordChange ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Save className="mr-2 h-4 w-4" />}
              Mettre à jour
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );

  if (loading) return <div className="min-h-screen flex items-center justify-center"><BarChart3 className="h-8 w-8 animate-spin text-primary" /></div>;

  return (
    <div className="mx-auto flex w-full max-w-[1600px] flex-col lg:flex-row lg:gap-8 px-4 sm:px-6 py-8 lg:py-12">
      <aside className="lg:sticky lg:top-24 lg:h-[calc(100vh-7rem)] lg:w-72 lg:shrink-0">
        <Card className="border-border/70 bg-card/80 backdrop-blur">
          <CardHeader className="pb-4">
            <CardTitle className="text-xl font-display">Administration</CardTitle>
            <CardDescription>Console de pilotage AIA Studio.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <nav className="hidden lg:block space-y-2">
              {adminSections.map((section) => {
                const Icon = section.icon;
                const active = activeSection === section.key;
                return (
                  <button
                    key={section.key}
                    onClick={() => setActiveSection(section.key)}
                    className={cn(
                      'w-full rounded-xl border px-4 py-3 text-left transition-all',
                      active
                        ? 'border-primary/30 bg-primary/10 text-primary shadow-lg shadow-primary/5'
                        : 'border-transparent bg-transparent text-muted-foreground hover:border-border hover:bg-muted/30 hover:text-foreground'
                    )}
                  >
                    <span className="flex items-center gap-3 font-bold text-sm">
                      <Icon className="h-4 w-4" /> {section.label}
                    </span>
                    <span className="mt-1 block pl-7 text-[11px] text-muted-foreground">{section.description}</span>
                  </button>
                );
              })}
            </nav>

            <div className="lg:hidden flex gap-2 overflow-x-auto pb-1">
              {adminSections.map((section) => {
                const Icon = section.icon;
                const active = activeSection === section.key;
                return (
                  <button
                    key={section.key}
                    onClick={() => setActiveSection(section.key)}
                    className={cn(
                      'shrink-0 rounded-full border px-3 py-2 text-xs font-bold transition-colors inline-flex items-center gap-2',
                      active ? 'border-primary/30 bg-primary/10 text-primary' : 'border-border bg-background text-muted-foreground'
                    )}
                  >
                    <Icon className="h-3.5 w-3.5" /> {section.label}
                  </button>
                );
              })}
            </div>

            <Button variant="outline" size="sm" onClick={handleLogout} className="w-full text-destructive hover:bg-destructive/10">
              <LogOut className="mr-2 h-4 w-4" /> Déconnexion
            </Button>
          </CardContent>
        </Card>
      </aside>

      <main className="mt-6 lg:mt-0 min-w-0 flex-1 space-y-8">
        <motion.div initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} className="flex flex-col md:flex-row md:items-end justify-between gap-4">
          <div>
            <h1 className="text-3xl font-bold font-display tracking-tight">Console d'Administration</h1>
            <p className="text-muted-foreground mt-1">Configurez les projets, équipes et cerveaux de votre agence multi-agents.</p>
          </div>
        </motion.div>

        {(error || successMsg) && (
          <div className="fixed bottom-8 right-4 sm:right-8 z-50 animate-in space-y-2 max-w-[calc(100vw-2rem)]">
            {error && (
              <Card className="bg-destructive/10 border-destructive/20 text-destructive p-4 flex items-center gap-3">
                <ShieldAlert className="h-5 w-5 shrink-0" /> {error}
              </Card>
            )}
            {successMsg && (
              <Card className="bg-emerald-500/10 border-emerald-500/20 text-emerald-500 p-4 flex items-center gap-3">
                <CheckCircle2 className="h-5 w-5 shrink-0" /> {successMsg}
              </Card>
            )}
          </div>
        )}

        {activeSection === 'projects' && renderProjectsPanel()}
        {activeSection === 'departments' && renderDepartmentsPanel()}
        {activeSection === 'settings' && renderSettingsPanel()}
        {activeSection === 'git' && renderGitPanel()}
        {activeSection === 'security' && renderSecurityPanel()}
      </main>
    </div>
  );
}
