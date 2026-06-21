'use client';

import { useState, useEffect, useRef } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  Terminal, 
  FileText, 
  MessagesSquare, 
  Trophy, 
  ChevronLeft, 
  Zap, 
  Loader2, 
  CheckCircle2, 
  AlertCircle,
  Bot,
  BookOpen,
  Database,
  Layers,
  Calendar,
  ClipboardList,
  Send,
  Users,
  Activity,
  Sparkles,
  PanelLeftOpen,
  PanelRightOpen,
  X,
  GitBranch,
  Download,
  FolderTree,
  FilePlus2,
  FolderPlus,
  Folder,
  FileCode2
} from 'lucide-react';
import { api } from '../../../lib/api';
import { connectProjectWs, WsEvent } from '../../../lib/websocket';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';
import { AuthGuard } from '@/components/auth-guard';

const CLEAN_MD_REGEX = /[#*_`>-]/g;

// Simple lightweight Markdown to HTML converter
function parseMarkdown(md: string = ''): string {
  if (!md) return '';
  let html = md.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  html = html.replace(/```([\s\S]*?)```/gm, (_, code) => `<pre><code>${code.trim()}</code></pre>`);
  html = html.replace(/^### (.*$)/gim, '<h3>$1</h3>');
  html = html.replace(/^## (.*$)/gim, '<h2>$1</h2>');
  html = html.replace(/^# (.*$)/gim, '<h1>$1</h1>');
  html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/`(.*?)`/g, '<code>$1</code>');
  html = html.replace(/^\s*[-*]\s+(.*)$/gim, '<li>$1</li>');
  html = html.replace(/(<li>.*<\/li>)/g, '<ul>$1</ul>');
  html = html.replace(/<\/ul>\s*<ul>/g, '');
  const paragraphs = html.split(/\n\n+/);
  return paragraphs.map((p) => {
    p = p.trim();
    if (!p) return '';
    if (p.startsWith('<h') || p.startsWith('<pre') || p.startsWith('<ul') || p.startsWith('<li>')) return p;
    return `<p>${p.replace(/\n/g, '<br />')}</p>`;
  }).join('');
}


interface GenerationSettings {
  root_path: string;
  require_technical_approval: boolean;
}

declare global {
  interface Window {
    mermaid?: {
      initialize: (config: Record<string, unknown>) => void;
      render: (id: string, definition: string) => Promise<{ svg: string }>;
    };
  }
}

function extractMermaidDiagram(content: string = ''): string {
  const fenced = content.match(/```mermaid\s*([\s\S]*?)```/i);
  if (fenced?.[1]) return fenced[1].trim();

  const trimmed = content.trim();
  if (trimmed.startsWith('erDiagram')) {
    return trimmed;
  }
  return '';
}

function looksUsableMermaidErDiagram(chart: string = ''): boolean {
  const normalized = chart.trim();
  if (!normalized.startsWith('erDiagram')) return false;
  const hasRelation = /(\|\|--o\{|\|\|--\|\{|o\{--\|\||o\{--o\{|\}\|--\|\{|\}\|--o\{)/.test(normalized);
  const openBraces = (normalized.match(/\{/g) || []).length;
  const closeBraces = (normalized.match(/\}/g) || []).length;
  return hasRelation && openBraces > 0 && openBraces === closeBraces;
}

function stripMermaidBlocks(content: string = ''): string {
  return content
    .replace(/```mermaid\s*[\s\S]*?```/gi, '')
    .replace(/erDiagram[\s\S]*?(?=\n\n|$)/i, '')
    .trim();
}

type DeliverableKey = 'cdc' | 'mcd' | 'architecture' | 'roadmap' | 'notes_synthese';
type ReviewRound = 'round1' | 'round2' | 'round3';

function buildRoundSynthesis(roundLabel: string, sections: Record<string, string>) {
  const filled = Object.entries(sections).filter(([, value]) => (value || '').trim());
  if (!filled.length) return '';
  return [
    `## Synthese ${roundLabel}`,
    '',
    ...filled.map(([key, value]) => `### ${key}\n${String(value).trim().slice(0, 1200)}`),
  ].join('\n');
}

function buildRoundDeliverables(project: any) {
  const critiques = project?.critiques || {};
  const finalDeliverables = project?.final_deliverables || {};

  const round1 = {
    cdc: project?.strategy_r1 || '',
    mcd: project?.engineering_r1 || '',
    architecture: project?.devops_r1 || '',
    roadmap: project?.ux_r1 || '',
    notes_synthese: buildRoundSynthesis('Round 1', {
      Strategie: project?.strategy_r1 || '',
      UX: project?.ux_r1 || '',
      Ingenierie: project?.engineering_r1 || '',
      DevOps: project?.devops_r1 || '',
    }),
  };

  const round2 = {
    cdc: critiques.strategy || '',
    mcd: critiques.engineering || '',
    architecture: critiques.devops || '',
    roadmap: critiques.ux || '',
    notes_synthese: buildRoundSynthesis('Round 2', {
      Strategie: critiques.strategy || '',
      UX: critiques.ux || '',
      Ingenierie: critiques.engineering || '',
      DevOps: critiques.devops || '',
    }),
  };

  const round3 = {
    cdc: finalDeliverables.cdc || '',
    mcd: finalDeliverables.mcd || '',
    architecture: finalDeliverables.architecture || '',
    roadmap: finalDeliverables.roadmap || '',
    notes_synthese: finalDeliverables.notes_synthese || '',
  };

  return { round1, round2, round3 };
}

function MermaidDiagram({ chart, emptyMessage = "Aucun diagramme Mermaid spécifique à ce projet n'a été généré pour cette ronde." }: { chart: string; emptyMessage?: string }) {
  const [svg, setSvg] = useState('');
  const [error, setError] = useState('');
  const chartIdRef = useRef(`mermaid-${Math.random().toString(36).slice(2)}`);

  useEffect(() => {
    let cancelled = false;

    async function loadMermaid() {
      if (!chart.trim()) return;
      setError('');
      setSvg('');
      try {
        if (!window.mermaid) {
          await new Promise<void>((resolve, reject) => {
            const existing = document.querySelector<HTMLScriptElement>('script[data-mermaid="true"]');
            if (existing) {
              existing.addEventListener('load', () => resolve(), { once: true });
              existing.addEventListener('error', () => reject(new Error('Mermaid indisponible')), { once: true });
              return;
            }
            const script = document.createElement('script');
            script.src = 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js';
            script.async = true;
            script.dataset.mermaid = 'true';
            script.onload = () => resolve();
            script.onerror = () => reject(new Error('Impossible de charger Mermaid'));
            document.head.appendChild(script);
          });
        }

        window.mermaid?.initialize({ startOnLoad: false, theme: 'dark', securityLevel: 'strict' });
        const result = await window.mermaid?.render(`${chartIdRef.current}-${Date.now()}`, chart);
        const renderedSvg = result?.svg || '';
        if (/Syntax error in text|mermaid version/i.test(renderedSvg)) {
          throw new Error('Le diagramme Mermaid généré est invalide. Le fallback textuel reste disponible ci-dessous.');
        }
        if (!cancelled && renderedSvg) setSvg(renderedSvg);
      } catch (err: any) {
        if (!cancelled) setError(err.message || 'Diagramme Mermaid invalide');
      }
    }

    loadMermaid();
    return () => { cancelled = true; };
  }, [chart]);

  if (!chart.trim()) {
    return (
      <div className="rounded-2xl border border-dashed border-border bg-muted/20 p-8 text-center text-sm text-muted-foreground">
        {emptyMessage}
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-3 rounded-2xl border border-destructive/20 bg-destructive/5 p-4">
        <p className="text-sm font-semibold text-destructive">{error}</p>
        <pre className="overflow-x-auto whitespace-pre text-xs text-muted-foreground">{chart}</pre>
      </div>
    );
  }

  return (
    <div className="min-h-[260px] overflow-auto rounded-2xl border border-primary/20 bg-[#090b12] p-4">
      {svg ? <div className="min-w-[520px]" dangerouslySetInnerHTML={{ __html: svg }} /> : <div className="flex h-64 items-center justify-center"><Loader2 className="h-6 w-6 animate-spin text-primary" /></div>}
    </div>
  );
}

export default function ProjectDashboard() {
  const params = useParams();
  const projectId = params.id as string;

  const [project, setProject] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [activeTab, setActiveTab] = useState<'live' | 'r1' | 'r2' | 'deliverables'>('live');
  const [activeDeliverable, setActiveDeliverable] = useState<DeliverableKey>('cdc');
  const [deliverableReviewRound, setDeliverableReviewRound] = useState<ReviewRound>('round3');
  const [deliverablesPanelOpen, setDeliverablesPanelOpen] = useState(false);
  const [contextPanelOpen, setContextPanelOpen] = useState(false);
  const [isAdminSession, setIsAdminSession] = useState(false);
  const [generationSettings, setGenerationSettings] = useState<GenerationSettings>({ root_path: '/opt', require_technical_approval: true });
  const [startingTechnicalDesign, setStartingTechnicalDesign] = useState(false);
  const [startingImplementation, setStartingImplementation] = useState(false);
  const [workspaceFiles, setWorkspaceFiles] = useState<{ path: string; name: string; is_dir?: boolean; kind?: string }[]>([]);
  const [selectedWorkspaceFile, setSelectedWorkspaceFile] = useState('');
  const [workspaceFileContent, setWorkspaceFileContent] = useState('');
  const [workspaceSavedContent, setWorkspaceSavedContent] = useState('');
  const [loadingWorkspaceFiles, setLoadingWorkspaceFiles] = useState(false);
  const [loadingWorkspaceFile, setLoadingWorkspaceFile] = useState(false);
  const [savingWorkspaceFile, setSavingWorkspaceFile] = useState(false);
  const [creatingWorkspaceEntry, setCreatingWorkspaceEntry] = useState(false);
  const [newWorkspacePath, setNewWorkspacePath] = useState('');
  const [workspaceMovePath, setWorkspaceMovePath] = useState('');

  const [logs, setLogs] = useState<{ text: string; type?: 'info' | 'success' | 'error' | 'system' }[]>([]);
  const [chatInput, setChatInput] = useState('');
  const [sendingMessage, setSendingMessage] = useState(false);
  const [conversation, setConversation] = useState<{
    kind?: 'agent' | 'user';
    agent: string;
    department: string;
    employee: { name: string; role: string; avatar: string };
    message: string;
    round?: number;
    phase?: string;
    target?: string;
    timestamp?: string;
  }[]>([]);
  const [runningAgents, setRunningAgents] = useState<Record<string, boolean>>({});
  const [agentStatuses, setAgentStatuses] = useState<Record<string, string>>({});
  const [wsStatus, setWsStatus] = useState<'connecting' | 'running' | 'idle' | 'error' | 'paused'>('idle');
  const [currentRound, setCurrentRound] = useState<number | null>(null);

  const selectedWorkspaceEntry = workspaceFiles.find((entry) => entry.path === selectedWorkspaceFile) || null;

  const wsCleanupRef = useRef<(() => void) | null>(null);
  const seenEventSequencesRef = useRef<Set<number>>(new Set());
  const logEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (logEndRef.current) logEndRef.current.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  useEffect(() => {
    if (!api.auth.isLoggedIn()) return;
    setIsAdminSession(true);
    api.admin.getGenerationSettings().then(setGenerationSettings).catch(() => {});
  }, []);

  useEffect(() => {
    const workspaceProjectDir = project?.final_deliverables?.implementation_workspace?.project_dir;
    if (!isAdminSession || !workspaceProjectDir) return;
    let cancelled = false;
    setLoadingWorkspaceFiles(true);
    api.projects.getWorkspaceTree(projectId)
      .then((data) => {
        if (cancelled) return;
        setWorkspaceFiles(data.files || []);
        if (!selectedWorkspaceFile && Array.isArray(data.files) && data.files.length > 0) {
          setSelectedWorkspaceFile(data.files[0].path);
        }
      })
      .catch(() => {})
      .finally(() => { if (!cancelled) setLoadingWorkspaceFiles(false); });
    return () => { cancelled = true; };
  }, [isAdminSession, project?.final_deliverables?.implementation_workspace?.project_dir, projectId, selectedWorkspaceFile]);

  useEffect(() => {
    if (!isAdminSession || !selectedWorkspaceFile) return;
    if (selectedWorkspaceEntry?.is_dir) {
      setWorkspaceFileContent('');
      setWorkspaceSavedContent('');
      setLoadingWorkspaceFile(false);
      return;
    }
    let cancelled = false;
    setLoadingWorkspaceFile(true);
    api.projects.getWorkspaceFile(projectId, selectedWorkspaceFile)
      .then((data) => {
        if (!cancelled) { setWorkspaceFileContent(data.content || ''); setWorkspaceSavedContent(data.content || ''); }
      })
      .catch(() => { if (!cancelled) setWorkspaceFileContent(''); })
      .finally(() => { if (!cancelled) setLoadingWorkspaceFile(false); });
    return () => { cancelled = true; };
  }, [isAdminSession, selectedWorkspaceFile, selectedWorkspaceEntry?.is_dir, projectId]);

  useEffect(() => {
    async function loadProject() {
      try {
        const data = await api.projects.get(projectId);
        setProject(data);
        if (data.status === 'completed') {
          setActiveTab('deliverables');
          setDeliverableReviewRound('round3');
        }
        startStreaming();
      } catch (err: any) {
        setError(err.message || 'Impossible de charger le projet.');
      } finally {
        setLoading(false);
      }
    }
    loadProject();
    return () => { if (wsCleanupRef.current) wsCleanupRef.current(); };
  }, [projectId]);

  const startStreaming = () => {
    if (wsCleanupRef.current) wsCleanupRef.current();
    setWsStatus('connecting');
    setLogs((prev) => prev.some((log) => log.text === 'Connexion au canal de streaming...') ? prev : [...prev, { text: 'Connexion au canal de streaming...', type: 'system' }]);

    const cleanup = connectProjectWs(projectId, handleWsEvent, () => {
      setWsStatus((current) => current === 'running' ? 'connecting' : 'idle');
      refreshProject();
    }, () => {
      refreshProject();
    }, { reconnect: true });
    wsCleanupRef.current = cleanup;
  };

  const refreshProject = async () => {
    try {
      const data = await api.projects.get(projectId);
      setProject(data);
      if (data.status === 'completed') setActiveTab('deliverables');
    } catch (err) {}
  };

  const handleStart = async () => {
    try {
      await api.projects.start(projectId);
      setProject((prev: any) => ({ ...prev, status: 'running', final_deliverables: null }));
      setWsStatus('running');
      setActiveTab('live');
      startStreaming();
    } catch (err: any) {
      setLogs((prev) => [...prev, { text: err.message || "Impossible de lancer l'analyse.", type: 'error' }]);
    }
  };

  const handleSendMessage = async () => {
    const content = chatInput.trim();
    if (!content) return;
    setSendingMessage(true);
    try {
      const result = await api.projects.sendMessage(projectId, content);
      if (result?.restart_triggered) {
        setWsStatus('running');
        setLogs((prev) => [...prev, {
          text: 'Demande de correction reçue. Une nouvelle passe corrective a été relancée automatiquement depuis les checkpoints déjà produits.',
          type: 'system',
        }]);
        startStreaming();
      } else {
        setLogs((prev) => [...prev, {
          text: 'Message ajouté au contexte du projet. Les employés l’utiliseront lors de la prochaine étape utile.',
          type: 'info',
        }]);
      }
      setChatInput('');
    } catch (err: any) {
      setLogs((prev) => [...prev, { text: err.message || 'Impossible d’envoyer le message.', type: 'error' }]);
    } finally {
      setSendingMessage(false);
    }
  };

  const handlePause = async () => {
    try {
      await api.projects.pause(projectId);
      if (wsCleanupRef.current) wsCleanupRef.current();
      setWsStatus('paused');
      setRunningAgents({});
      setAgentStatuses({});
      setProject((prev: any) => ({
        ...prev,
        status: 'paused',
        final_deliverables: { error: "Analyse mise en pause par l'utilisateur." },
      }));
      setLogs((prev) => [...prev, { text: "Analyse mise en pause. Vous pourrez la reprendre plus tard.", type: 'system' }]);
    } catch (err: any) {
      setLogs((prev) => [...prev, { text: err.message || "Impossible de mettre l'analyse en pause.", type: 'error' }]);
    }
  };

  const handleRestart = async () => {
    try {
      const data = await api.projects.restart(projectId);
      setProject(data);
      setLogs([]);
      setConversation([]);
      seenEventSequencesRef.current.clear();
      setRunningAgents({});
      setAgentStatuses({});
      setActiveTab('live');
      await api.projects.start(projectId);
      setProject((prev: any) => ({ ...prev, status: 'running', final_deliverables: null }));
      startStreaming();
    } catch (err: any) {
      setLogs((prev) => [...prev, { text: err.message || "Impossible de relancer l'analyse.", type: 'error' }]);
    }
  };

  const handleStartTechnicalDesign = async () => {
    if (!isAdminSession) return;
    const needsApproval = generationSettings.require_technical_approval;
    if (needsApproval) {
      const confirmed = window.confirm(
        `La phase conception technique va initialiser un workspace réel dans ${generationSettings.root_path}.\n\nContinuer maintenant ?`
      );
      if (!confirmed) return;
    }

    setStartingTechnicalDesign(true);
    try {
      const updatedProject = await api.projects.startTechnicalDesign(projectId, needsApproval);
      setProject(updatedProject);
      setActiveTab('deliverables');
      setLogs((prev) => [...prev, { text: 'Workspace de conception technique initialisé. Les futures générations resteront confinées au dossier du projet.', type: 'success' }]);
    } catch (err: any) {
      setLogs((prev) => [...prev, { text: err.message || "Impossible d'initialiser la conception technique.", type: 'error' }]);
    } finally {
      setStartingTechnicalDesign(false);
    }
  };

  const handleStartImplementation = async () => {
    if (!isAdminSession) return;
    setStartingImplementation(true);
    try {
      await api.projects.startImplementation(projectId, true);
      setLogs((prev) => [...prev, { text: 'Phase applicative lancée. Les employés construisent le repo dans le workspace projet.', type: 'system' }]);
      setActiveTab('live');
    } catch (err: any) {
      setLogs((prev) => [...prev, { text: err.message || "Impossible de lancer la phase applicative.", type: 'error' }]);
    } finally {
      setStartingImplementation(false);
    }
  };

  const handleDownloadMarkdown = async () => {
    try {
      await api.projects.downloadMarkdownExport(projectId);
    } catch (err: any) {
      setLogs((prev) => [...prev, { text: err.message || 'Impossible de télécharger le markdown.', type: 'error' }]);
    }
  };

  const handleDownloadWorkspace = async () => {
    try {
      await api.projects.downloadWorkspaceArchive(projectId);
    } catch (err: any) {
      setLogs((prev) => [...prev, { text: err.message || 'Impossible de télécharger le workspace.', type: 'error' }]);
    }
  };

  const handleSaveWorkspaceFile = async () => {
    if (!selectedWorkspaceFile) return;
    setSavingWorkspaceFile(true);
    try {
      await api.projects.saveWorkspaceFile(projectId, selectedWorkspaceFile, workspaceFileContent);
      setWorkspaceSavedContent(workspaceFileContent);
      setLogs((prev) => [...prev, { text: `Fichier sauvegardé: ${selectedWorkspaceFile}`, type: 'success' }]);
    } catch (err: any) {
      setLogs((prev) => [...prev, { text: err.message || 'Impossible de sauvegarder ce fichier.', type: 'error' }]);
    } finally {
      setSavingWorkspaceFile(false);
    }
  };

  const handleCreateWorkspaceEntry = async (isDirectory: boolean) => {
    const filePath = newWorkspacePath.trim();
    if (!filePath) return;
    setCreatingWorkspaceEntry(true);
    try {
      await api.projects.createWorkspaceEntry(projectId, filePath, isDirectory, '');
      const data = await api.projects.getWorkspaceTree(projectId);
      setWorkspaceFiles(data.files || []);
      setNewWorkspacePath('');
      setSelectedWorkspaceFile(filePath);
      setWorkspaceMovePath(filePath);
      setLogs((prev) => [...prev, { text: `${isDirectory ? 'Dossier' : 'Fichier'} créé: ${filePath}`, type: 'success' }]);
    } catch (err: any) {
      setLogs((prev) => [...prev, { text: err.message || `Impossible de créer le ${isDirectory ? 'dossier' : 'fichier'}.`, type: 'error' }]);
    } finally {
      setCreatingWorkspaceEntry(false);
    }
  };

  const handleDeleteWorkspaceEntry = async () => {
    if (!selectedWorkspaceFile) return;
    const confirmed = window.confirm(`Supprimer ${selectedWorkspaceFile} du workspace projet ?`);
    if (!confirmed) return;
    setCreatingWorkspaceEntry(true);
    try {
      await api.projects.deleteWorkspaceEntry(projectId, selectedWorkspaceFile);
      const deletedPath = selectedWorkspaceFile;
      const data = await api.projects.getWorkspaceTree(projectId);
      const files = data.files || [];
      setWorkspaceFiles(files);
      setSelectedWorkspaceFile(files[0]?.path || '');
      if (!files.length) {
        setWorkspaceFileContent('');
        setWorkspaceSavedContent('');
      }
      setLogs((prev) => [...prev, { text: `Entrée supprimée: ${deletedPath}`, type: 'success' }]);
    } catch (err: any) {
      setLogs((prev) => [...prev, { text: err.message || 'Impossible de supprimer cette entrée.', type: 'error' }]);
    } finally {
      setCreatingWorkspaceEntry(false);
    }
  };

  const handleMoveWorkspaceEntry = async () => {
    const oldPath = selectedWorkspaceFile.trim();
    const newPath = workspaceMovePath.trim();
    if (!oldPath || !newPath || oldPath === newPath) return;
    setCreatingWorkspaceEntry(true);
    try {
      await api.projects.moveWorkspaceEntry(projectId, oldPath, newPath);
      const data = await api.projects.getWorkspaceTree(projectId);
      setWorkspaceFiles(data.files || []);
      setSelectedWorkspaceFile(newPath);
      setWorkspaceMovePath(newPath);
      setLogs((prev) => [...prev, { text: `Entrée déplacée: ${oldPath} -> ${newPath}`, type: 'success' }]);
    } catch (err: any) {
      setLogs((prev) => [...prev, { text: err.message || 'Impossible de renommer cette entrée.', type: 'error' }]);
    } finally {
      setCreatingWorkspaceEntry(false);
    }
  };

  const handleWsEvent = (event: WsEvent) => {
    if (event.sequence && seenEventSequencesRef.current.has(event.sequence)) return;
    if (event.sequence) seenEventSequencesRef.current.add(event.sequence);

    switch (event.type) {
      case 'workflow_started':
        setWsStatus('running');
        setCurrentRound(null);
        setProject((prev: any) => ({ ...prev, status: 'running', final_deliverables: null }));
        setLogs((prev) => [...prev, { text: event.message || 'Analyse lancée côté serveur.', type: 'system' }]);
        break;
      case 'round_start':
        setWsStatus('running');
        setCurrentRound(event.round || null);
        setAgentStatuses((prev) => ({ ...prev, orchestrator: event.message?.toLowerCase().includes('synthèse') ? 'Synthétise' : 'Coordonne' }));
        setLogs((prev) => [...prev, { text: `── ROUND ${event.round} : ${event.message || 'Début'} ──`, type: 'info' }]);
        break;
      case 'agent_start':
        setRunningAgents((prev) => ({ ...prev, [event.agent || '']: true }));
        setAgentStatuses((prev) => ({ ...prev, [event.agent || '']: (event.round || 1) >= 2 ? 'Réfléchit / critique' : 'Rédige' }));
        setLogs((prev) => [...prev, { text: `[Département ${event.agent?.toUpperCase()}] Début de la rédaction...`, type: 'info' }]);
        break;
      case 'agent_complete':
        setRunningAgents((prev) => ({ ...prev, [event.agent || '']: false }));
        setAgentStatuses((prev) => ({ ...prev, [event.agent || '']: 'Attend critique' }));
        if (event.content && event.agent) {
          const agentKey = event.agent;
          const content = event.content;
          setProject((prev: any) => {
            if (!prev) return prev;
            if (event.round === 1) {
              const field = `${agentKey}_r1`;
              return { ...prev, [field]: content };
            }
            if ((event.round || 1) >= 2) {
              return {
                ...prev,
                critiques: { ...(prev.critiques || {}), [agentKey]: content },
              };
            }
            return prev;
          });
        }
        setLogs((prev) => [...prev, { text: `[Département ${event.agent?.toUpperCase()}] Rédaction terminée.`, type: 'success' }]);
        break;
      case 'user_message':
        if (event.content || event.message) {
          setConversation((prev) => [...prev, {
            kind: 'user',
            agent: 'user',
            department: 'Client',
            employee: { name: event.author || 'Utilisateur', role: 'Client / chef de projet', avatar: 'US' },
            message: event.content || event.message || '',
            timestamp: event.timestamp,
          }]);
          setLogs((prev) => [...prev, { text: 'Nouvelle contribution utilisateur ajoutée au contexte.', type: 'system' }]);
        }
        break;
      case 'employee_message':
        if (event.employee && event.message && event.agent && event.department) {
          setConversation((prev) => [...prev, {
            kind: 'agent',
            agent: event.agent || '',
            department: event.department || '',
            employee: event.employee!,
            message: event.message || '',
            round: event.round,
            phase: event.phase,
            target: event.target,
            timestamp: event.timestamp,
          }]);
        }
        break;
      case 'agent_error':
        setRunningAgents((prev) => ({ ...prev, [event.agent || '']: false }));
        setLogs((prev) => [...prev, { text: `[Département ${event.agent?.toUpperCase()}] Erreur : ${event.error}`, type: 'error' }]);
        break;
      case 'implementation_status':
        if (event.pipeline) {
          setProject((prev: any) => ({
            ...prev,
            final_deliverables: { ...(prev?.final_deliverables || {}), implementation_pipeline: event.pipeline },
          }));
        }
        setLogs((prev) => [...prev, { text: event.message || 'Mise à jour de la phase applicative.', type: 'system' }]);
        break;
      case 'implementation_complete':
        if (event.pipeline || event.workspace) {
          setProject((prev: any) => ({
            ...prev,
            final_deliverables: {
              ...(prev?.final_deliverables || {}),
              ...(event.pipeline ? { implementation_pipeline: event.pipeline } : {}),
              ...(event.workspace ? { implementation_workspace: event.workspace } : {}),
            },
          }));
        }
        setLogs((prev) => [...prev, { text: event.message || 'Phase applicative terminée.', type: 'success' }]);
        break;
      case 'implementation_error':
        if (event.pipeline) {
          setProject((prev: any) => ({
            ...prev,
            final_deliverables: { ...(prev?.final_deliverables || {}), implementation_pipeline: event.pipeline },
          }));
        }
        setLogs((prev) => [...prev, { text: event.message || 'Erreur pendant la phase applicative.', type: 'error' }]);
        break;
      case 'workflow_complete':
        setLogs((prev) => [...prev, { text: 'Workflow terminé avec succès !', type: 'success' }]);
        setWsStatus('idle');
        setCurrentRound(null);
        setRunningAgents({});
        setAgentStatuses({ strategy: 'Terminé', ux: 'Terminé', engineering: 'Terminé', devops: 'Terminé', orchestrator: 'Terminé' });
        setProject((prev: any) => ({
          ...prev,
          status: 'completed',
          final_deliverables: {
            ...(prev?.final_deliverables || {}),
            ...(event.deliverables || {}),
            ...(event.pipeline ? { implementation_pipeline: event.pipeline } : {}),
            ...(event.workspace ? { implementation_workspace: event.workspace } : {}),
          },
        }));
        if (event.deliverables || event.pipeline || event.workspace) {
          setActiveTab('deliverables');
          setDeliverableReviewRound('round3');
        }
        break;
      case 'workflow_paused':
        setLogs((prev) => [...prev, { text: event.message || 'Analyse mise en pause.', type: 'system' }]);
        setWsStatus('paused');
        setRunningAgents({});
        setAgentStatuses((prev) => ({ ...prev, orchestrator: 'En pause' }));
        setProject((prev: any) => ({
          ...prev,
          status: 'paused',
          final_deliverables: {
            ...(prev?.final_deliverables || {}),
            ...(event.pipeline ? { implementation_pipeline: event.pipeline } : {}),
            ...(event.workspace ? { implementation_workspace: event.workspace } : {}),
            error: event.message || 'Analyse mise en pause.',
          },
        }));
        break;
      case 'workflow_error':
      case 'error':
        setLogs((prev) => [...prev, { text: `Échec du workflow : ${event.message || event.error}`, type: 'error' }]);
        setWsStatus('error');
        setRunningAgents({});
        setAgentStatuses((prev) => ({ ...prev, orchestrator: 'Bloqué' }));
        setProject((prev: any) => ({
          ...prev,
          status: 'failed',
          final_deliverables: {
            ...(prev?.final_deliverables || {}),
            ...(event.pipeline ? { implementation_pipeline: event.pipeline } : {}),
            ...(event.workspace ? { implementation_workspace: event.workspace } : {}),
            error: event.message || event.error,
          },
        }));
        break;
    }
  };

  if (loading) return <AuthGuard><div className="min-h-screen bg-background flex items-center justify-center"><Loader2 className="h-8 w-8 animate-spin text-primary" /></div></AuthGuard>;
  if (error || !project) return (
    <AuthGuard>
    <div className="min-h-screen flex items-center justify-center p-6">
      <Card className="max-w-md border-destructive/20">
        <CardHeader><CardTitle className="text-destructive">Erreur</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">{error || 'Session introuvable'}</p>
          <Button asChild variant="outline" className="w-full"><Link href="/">Retour à l'accueil</Link></Button>
        </CardContent>
      </Card>
    </div>
    </AuthGuard>
  );

  const deliverables = project.final_deliverables || {};
  const implementationPipeline = deliverables.implementation_pipeline || null;
  const workspaceInfo = deliverables.implementation_workspace || (implementationPipeline?.project_dir ? {
    project_dir: implementationPipeline.project_dir,
    root_path: implementationPipeline.root_path || '',
    files: implementationPipeline.generated_files || [],
    repo_name: implementationPipeline.project_dir.split('/').filter(Boolean).pop() || 'workspace',
  } : null);
  const persistedWorkflowError = (project.status === 'failed' || project.status === 'paused') ? deliverables.error : '';
  const employeeRoster = [
    { agent: 'strategy', department: 'Stratégie', name: 'Aminata', role: 'Lead Growth', avatar: 'AG' },
    { agent: 'strategy', department: 'Stratégie', name: 'Noam', role: 'Analyste marché', avatar: 'NM' },
    { agent: 'ux', department: 'UX', name: 'Maya', role: 'UX Researcher', avatar: 'UX' },
    { agent: 'ux', department: 'UX', name: 'Lina', role: 'Product Designer', avatar: 'PD' },
    { agent: 'engineering', department: 'Ingénierie', name: 'Elias', role: 'Architecte logiciel', avatar: 'AR' },
    { agent: 'engineering', department: 'Ingénierie', name: 'Sara', role: 'Data modeler', avatar: 'DB' },
    { agent: 'devops', department: 'DevOps', name: 'Karim', role: 'DevSecOps', avatar: 'DS' },
    { agent: 'devops', department: 'DevOps', name: 'Inès', role: 'Cloud engineer', avatar: 'CE' },
  ];
  const roundDeliverables = buildRoundDeliverables(project);
  const deliverableRoundLabels: Record<ReviewRound, string> = {
    round1: 'Round 1',
    round2: 'Round 2',
    round3: 'Round 3',
  };
  const selectedRoundDeliverables = roundDeliverables[deliverableReviewRound];
  const liveDeliverableCards = [
    { key: 'cdc', label: 'CDC', value: deliverables.cdc || project.strategy_r1 },
    { key: 'mcd', label: 'MCD', value: deliverables.mcd || project.engineering_r1 },
    { key: 'architecture', label: 'Architecture', value: deliverables.architecture || project.devops_r1 },
    { key: 'roadmap', label: 'Roadmap', value: deliverables.roadmap || project.critiques?.strategy },
  ];
  const activeLiveDeliverable = liveDeliverableCards.find((item) => item.key === activeDeliverable)?.value || deliverables[activeDeliverable] || '';
  const selectedDeliverableContent = String(selectedRoundDeliverables?.[activeDeliverable] || '*Livrable non généré pour cette ronde.*');
  const mcdSource = String(selectedRoundDeliverables?.mcd || deliverables.mcd || project.engineering_r1 || '');
  const extractedMcdMermaid = extractMermaidDiagram(mcdSource);
  const mcdMermaid = looksUsableMermaidErDiagram(extractedMcdMermaid) ? extractedMcdMermaid : '';
  const mcdMermaidEmptyMessage = mcdSource.trim()
    ? "Aucun diagramme Mermaid spécifique à ce projet n'a été généré pour cette ronde. Le MCD textuel reste affiché ci-dessous."
    : "Aucun MCD n'a été généré pour cette ronde.";
  const hasRound1 = Boolean(project.strategy_r1 || project.ux_r1 || project.engineering_r1 || project.devops_r1);
  const round1Complete = Boolean(project.strategy_r1 && project.ux_r1 && project.engineering_r1 && project.devops_r1);
  const critiques = project.critiques || {};
  const hasRound2 = Boolean(critiques.strategy || critiques.ux || critiques.engineering || critiques.devops);
  const round2Complete = Boolean(critiques.strategy && critiques.ux && critiques.engineering && critiques.devops);
  const hasDeliverables = Boolean(deliverables.cdc || deliverables.mcd || deliverables.architecture || deliverables.roadmap);

  const getTabProgress = (tabId: 'live' | 'r1' | 'r2' | 'deliverables') => {
    if (project.status === 'failed') {
      if ((tabId === 'r1' && currentRound === 1) || (tabId === 'r2' && (currentRound || 0) >= 2) || (tabId === 'deliverables' && !hasDeliverables)) return 'error';
    }
    if (tabId === 'live') return wsStatus === 'running' ? 'running' : project.status === 'completed' ? 'complete' : 'idle';
    if (tabId === 'r1') return round1Complete ? 'complete' : currentRound === 1 || hasRound1 ? 'running' : 'pending';
    if (tabId === 'r2') return round2Complete ? 'complete' : (currentRound || 0) >= 2 || hasRound2 ? 'running' : 'pending';
    if (tabId === 'deliverables') return hasDeliverables || project.status === 'completed' ? 'complete' : currentRound && currentRound >= 3 ? 'running' : 'pending';
    return 'pending';
  };

  const renderTabProgress = (status: string) => {
    if (status === 'complete') return <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />;
    if (status === 'running') return <span className="relative flex h-3.5 w-3.5"><span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary/60 opacity-75" /><span className="relative inline-flex h-3.5 w-3.5 rounded-full bg-primary shadow shadow-primary/40" /></span>;
    if (status === 'error') return <AlertCircle className="h-3.5 w-3.5 text-destructive" />;
    return <span className="h-2.5 w-2.5 rounded-full border border-muted-foreground/40 bg-muted/40" />;
  };

  let tabContent = null;

  if (activeTab === 'live') {
    tabContent = (
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -10 }}
        className="grid grid-cols-1 gap-6 xl:grid-cols-1"
      >
        <Card className="border-border/40 shadow-2xl overflow-hidden min-w-0">
          <CardHeader className="border-b border-border/40 py-4 flex flex-row items-center justify-between bg-muted/20">
            <CardTitle className="text-sm flex items-center gap-2">
              <MessagesSquare className="h-4 w-4 text-primary" /> Débat inter-départements
            </CardTitle>
            <span className="text-[10px] uppercase tracking-widest text-muted-foreground">Chat participatif</span>
          </CardHeader>
          <CardContent className="p-0 flex flex-col h-[980px] xl:h-[calc(100vh-230px)] xl:min-h-[980px]">
            <div className="flex-1 overflow-y-auto p-5 space-y-4 scrollbar-thin scrollbar-thumb-muted-foreground/20 bg-gradient-to-b from-background to-muted/10">
              {conversation.map((item, i) => (
                <motion.div
                  key={`${item.timestamp}-${i}`}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  className={cn(
                    'flex gap-3',
                    item.kind === 'user' ? 'justify-end' : item.agent === 'orchestrator' ? 'justify-center' : 'justify-start'
                  )}
                >
                  {item.kind !== 'user' && (
                    <div
                      className={cn(
                        'h-10 w-10 rounded-xl flex items-center justify-center text-[10px] font-bold border shrink-0',
                        item.agent === 'orchestrator' ? 'bg-primary/15 text-primary border-primary/30' : 'bg-muted text-foreground border-border'
                      )}
                    >
                      {item.employee.avatar}
                    </div>
                  )}
                  <div
                    className={cn(
                      'max-w-[88%] rounded-2xl border p-4 shadow-sm',
                      item.kind === 'user'
                        ? 'bg-blue-500/10 border-blue-500/25'
                        : item.phase === 'system_step'
                          ? 'bg-muted/25 border-border/50 opacity-80'
                          : item.agent === 'orchestrator'
                            ? 'bg-primary/10 border-primary/20'
                            : 'bg-card/80 border-border/60'
                    )}
                  >
                    <div className="flex flex-wrap items-center gap-2 mb-2">
                      <span className="font-bold text-sm">{item.employee.name}</span>
                      <span className="text-[10px] text-muted-foreground">{item.employee.role}</span>
                      <span className="text-[10px] px-2 py-0.5 rounded-full bg-muted border border-border text-muted-foreground">
                        {item.kind === 'user'
                          ? 'Contribution utilisateur'
                          : item.phase === 'system_step'
                            ? `Étape système${item.round ? ` · Round ${item.round}` : ''}`
                            : `${item.department}${item.round ? ` · Round ${item.round}` : ''}`}
                      </span>
                      {item.target && <span className="text-[10px] text-primary">→ {item.target}</span>}
                    </div>
                    <p className="text-sm leading-relaxed text-muted-foreground whitespace-pre-wrap">{item.message}</p>
                  </div>
                </motion.div>
              ))}
              {conversation.length === 0 && (
                <div className="h-full flex flex-col items-center justify-center text-center text-muted-foreground/50 py-20">
                  <Bot className="h-10 w-10 mb-3" />
                  <p className="font-medium">La salle de réunion est prête.</p>
                  <p className="text-sm">Lance l'analyse ou ajoute une précision pour participer au travail.</p>
                </div>
              )}
              <div ref={logEndRef} />
            </div>
            <div className="border-t border-border/50 bg-card/95 p-4">
              <div className="flex gap-3">
                <textarea
                  value={chatInput}
                  onChange={(event) => setChatInput(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' && !event.shiftKey) {
                      event.preventDefault();
                      handleSendMessage();
                    }
                  }}
                  placeholder="Ajouter une précision, contrainte, correction ou nouvelle exigence..."
                  className="min-h-[44px] max-h-32 flex-1 resize-none rounded-xl border border-border bg-background px-4 py-3 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
                />
                <Button onClick={handleSendMessage} disabled={!chatInput.trim() || sendingMessage} className="h-11 shrink-0 px-4">
                  {sendingMessage ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                </Button>
              </div>
              <p className="mt-2 text-[10px] text-muted-foreground">
                Entrée pour envoyer, Shift+Entrée pour une nouvelle ligne. Les agents tiendront compte du message aux prochaines étapes.
              </p>
            </div>
          </CardContent>
        </Card>
      </motion.div>
    );
  } else if (activeTab === 'r1' || activeTab === 'r2') {

    tabContent = (
      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {[
          { key: 'strategy', title: 'Stratégie', content: activeTab === 'r1' ? project.strategy_r1 : project.critiques?.strategy },
          { key: 'ux', title: 'UX', content: activeTab === 'r1' ? project.ux_r1 : project.critiques?.ux },
          { key: 'engineering', title: 'Ingénierie', content: activeTab === 'r1' ? project.engineering_r1 : project.critiques?.engineering },
          { key: 'devops', title: 'DevOps', content: activeTab === 'r1' ? project.devops_r1 : project.critiques?.devops },
        ].map((sec) => (
          <Card key={sec.key} className="h-[400px] flex flex-col">
            <CardHeader className="border-b border-border/50 py-3">
              <CardTitle className="text-sm flex justify-between items-center">
                {sec.title}
                <span className="text-[10px] font-normal text-muted-foreground">{activeTab === 'r1' ? 'Analysis' : 'Critique'}</span>
              </CardTitle>
            </CardHeader>
            <CardContent className="flex-1 overflow-y-auto p-5 prose prose-sm max-w-none scrollbar-thin">
              <div dangerouslySetInnerHTML={{ __html: parseMarkdown(sec.content || '*En attente de génération...*') }} />
            </CardContent>
          </Card>
        ))}
      </motion.div>
    );
  } else {
    tabContent = (
      <motion.div initial={{ opacity: 0, scale: 0.98 }} animate={{ opacity: 1, scale: 1 }} className="grid grid-cols-1 lg:grid-cols-4 gap-8 items-start">
        <div className="lg:col-span-1 space-y-4">
          <Card className="border-border/60">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm">Vue par ronde</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {([
                { key: 'round1', label: 'Round 1 · Analyses initiales' },
                { key: 'round2', label: 'Round 2 · Critiques' },
                { key: 'round3', label: 'Round 3 · Synthèse finale' },
              ] as { key: ReviewRound; label: string }[]).map((roundOption) => (
                <button
                  key={roundOption.key}
                  onClick={() => setDeliverableReviewRound(roundOption.key)}
                  className={cn(
                    'w-full rounded-xl border px-4 py-3 text-left text-sm font-semibold transition-all',
                    deliverableReviewRound === roundOption.key
                      ? 'border-primary/20 bg-primary/5 text-primary'
                      : 'border-border/60 bg-muted/20 text-muted-foreground hover:text-foreground'
                  )}
                >
                  {roundOption.label}
                </button>
              ))}
            </CardContent>
          </Card>

          <div className="space-y-2">
            {[
              { key: 'cdc', label: 'Spécifications', icon: BookOpen },
              { key: 'mcd', label: 'Modélisation MCD', icon: Database },
              { key: 'architecture', label: 'Architecture', icon: Layers },
              { key: 'roadmap', label: 'Roadmap MVP', icon: Calendar },
              { key: 'notes_synthese', label: 'Synthèse', icon: ClipboardList },
            ].map((item) => (
              <button
                key={item.key}
                onClick={() => setActiveDeliverable(item.key as DeliverableKey)}
                className={cn(
                  'w-full flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-semibold transition-all border',
                  activeDeliverable === item.key
                    ? 'bg-primary/5 text-primary border-primary/20'
                    : 'bg-transparent border-transparent text-muted-foreground hover:bg-muted/50'
                )}
              >
                <item.icon className="h-4 w-4" /> {item.label}
              </button>
            ))}
          </div>
        </div>

        <div className="lg:col-span-3 space-y-4">
          {workspaceInfo && (
            <Card className="border-primary/20 bg-primary/5">
              <CardHeader className="pb-3">
                <CardTitle className="text-base flex items-center gap-2">
                  <GitBranch className="h-4 w-4 text-primary" /> Workspace technique
                </CardTitle>
                <CardDescription>
                  Phase conception technique initialisée avec garde-fou local. Les employés ne pourront écrire que dans ce dossier.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-3 text-sm text-muted-foreground">
                <p><strong>Dossier projet :</strong> <code>{workspaceInfo.project_dir}</code></p>
                <p><strong>Racine :</strong> <code>{workspaceInfo.root_path}</code></p>
                <p><strong>Fichiers initialisés :</strong> {Array.isArray(workspaceInfo.files) ? workspaceInfo.files.length : 0}</p>
                <div className="flex flex-wrap gap-2">
                  <Button type="button" variant="outline" size="sm" className="gap-2" onClick={handleDownloadMarkdown}>
                    <Download className="h-3.5 w-3.5" /> Export Markdown
                  </Button>
                  {isAdminSession && (
                    <>
                      <Button asChild type="button" variant="outline" size="sm" className="gap-2">
                        <Link href={`/projects/${projectId}/workspace`}>
                          <FolderTree className="h-3.5 w-3.5" /> Ouvrir OpenHands
                        </Link>
                      </Button>
                      <Button type="button" variant="outline" size="sm" className="gap-2" onClick={handleDownloadWorkspace}>
                        <FolderTree className="h-3.5 w-3.5" /> Télécharger le repo ZIP
                      </Button>
                    </>
                  )}
                </div>
              </CardContent>
            </Card>
          )}

          {implementationPipeline && (
            <Card className="border-border/60 bg-muted/20">
              <CardHeader className="pb-3">
                <CardTitle className="text-base flex items-center gap-2">
                  <Sparkles className="h-4 w-4 text-primary" /> Pipeline applicatif
                </CardTitle>
                <CardDescription>
                  Statut actuel : <strong>{implementationPipeline.status}</strong>
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-3 text-sm text-muted-foreground">
                {Array.isArray(implementationPipeline.phases) && implementationPipeline.phases.map((phase: any) => (
                  <div key={phase.key} className="flex items-center justify-between rounded-lg border border-border/60 px-3 py-2">
                    <span>{phase.label}</span>
                    <span className="text-xs uppercase tracking-widest text-primary">{phase.status}</span>
                  </div>
                ))}
                {implementationPipeline.last_error && (
                  <p className="text-destructive text-xs">{implementationPipeline.last_error}</p>
                )}
              </CardContent>
            </Card>
          )}





          <Card className="min-h-[600px] border-border/60 shadow-xl">
            <CardHeader className="border-b border-border/40 space-y-3">
              <div className="flex items-center justify-between gap-4">
                <CardTitle className="text-xl capitalize flex items-center gap-3">
                  {activeDeliverable === 'cdc' ? <BookOpen className="h-5 w-5 text-primary" /> :
                   activeDeliverable === 'mcd' ? <Database className="h-5 w-5 text-primary" /> :
                   activeDeliverable === 'architecture' ? <Layers className="h-5 w-5 text-primary" /> :
                   activeDeliverable === 'roadmap' ? <Calendar className="h-5 w-5 text-primary" /> :
                   <ClipboardList className="h-5 w-5 text-primary" />}
                  {activeDeliverable.replace('_', ' ')}
                </CardTitle>
                <span className="rounded-full border border-primary/20 bg-primary/10 px-3 py-1 text-xs font-bold text-primary">
                  {deliverableRoundLabels[deliverableReviewRound]}
                </span>
              </div>
              <p className="text-sm text-muted-foreground">Retrouve la matière produite à chaque étape sans perdre le contexte de la ronde finale.</p>
            </CardHeader>
            <CardContent className="space-y-6 p-8">
              {activeDeliverable === 'mcd' && (
                <Card className="border-primary/20 bg-primary/5">
                  <CardHeader className="pb-3">
                    <CardTitle className="text-sm flex items-center gap-2">
                      <GitBranch className="h-4 w-4 text-primary" /> Graph Mermaid ERD
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <MermaidDiagram chart={mcdMermaid} emptyMessage={mcdMermaidEmptyMessage} />
                  </CardContent>
                </Card>
              )}
              <div className="prose prose-slate dark:prose-invert max-w-none">
                <div
                  dangerouslySetInnerHTML={{
                    __html: parseMarkdown(
                      activeDeliverable === 'mcd'
                        ? stripMermaidBlocks(selectedDeliverableContent) || '*Description textuelle non générée.*'
                        : selectedDeliverableContent
                    )
                  }}
                />
              </div>
            </CardContent>
          </Card>
        </div>
      </motion.div>
    );
  }

  return (
    <AuthGuard>
      <div className="contents">
        <motion.div
        className="flex flex-col min-h-screen origin-left"
        animate={{ scale: deliverablesPanelOpen ? 0.985 : 1, x: deliverablesPanelOpen ? -18 : 0 }}
        transition={{ type: 'spring', stiffness: 260, damping: 28 }}
      >
        <header className="border-b border-border/60 bg-muted/20">
          <div className="max-w-7xl mx-auto px-6 py-8">
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-6">
              <div className="space-y-2">
                <Link href="/" className="inline-flex items-center text-xs text-muted-foreground hover:text-foreground transition-colors mb-2">
                  <ChevronLeft className="mr-1 h-3 w-3" /> Retour
                </Link>
                <h1 className="text-2xl font-bold font-display tracking-tight flex items-center gap-3">
                  {project.title}
                  <span
                    className={cn(
                      'text-[10px] px-2 py-0.5 rounded-full font-bold uppercase tracking-widest',
                      project.status === 'completed'
                        ? 'bg-emerald-500/10 text-emerald-500 border border-emerald-500/20'
                        : project.status === 'running'
                          ? 'bg-primary/10 text-primary border border-primary/20 animate-pulse'
                          : project.status === 'failed'
                            ? 'bg-destructive/10 text-destructive border border-destructive/20'
                            : project.status === 'paused'
                              ? 'bg-amber-500/10 text-amber-500 border border-amber-500/20'
                              : 'bg-muted text-muted-foreground border border-border'
                    )}
                  >
                    {project.status === 'completed'
                      ? 'Terminé'
                      : project.status === 'running'
                        ? 'En cours'
                        : project.status === 'failed'
                          ? 'Échoué'
                          : project.status === 'paused'
                            ? 'En pause'
                            : 'En attente'}
                  </span>
                </h1>
                <p className="text-sm text-muted-foreground line-clamp-1 max-w-2xl">{project.input_text}</p>
              </div>

              <div className="flex gap-3">
                {(project.status === 'pending' || project.status === 'failed' || project.status === 'paused') && wsStatus !== 'running' && (
                  <Button onClick={handleStart} className="gap-2">
                    <Zap className="h-4 w-4" /> {project.status === 'paused' ? "Reprendre l'analyse" : "Lancer l'Analyse"}
                  </Button>
                )}
                {project.status === 'completed' && wsStatus !== 'running' && (
                  <>
                    {isAdminSession && workspaceInfo && (
                      <Button asChild variant="outline" className="gap-2">
                        <Link href={`/projects/${projectId}/workspace`}>
                          <FolderTree className="h-4 w-4" />
                          Ouvrir OpenHands
                        </Link>
                      </Button>
                    )}
                    {isAdminSession && !workspaceInfo && (
                      <Button onClick={handleStartTechnicalDesign} variant="outline" className="gap-2" disabled={startingTechnicalDesign}>
                        {startingTechnicalDesign ? <Loader2 className="h-4 w-4 animate-spin" /> : <GitBranch className="h-4 w-4" />}
                        Lancer la conception technique
                      </Button>
                    )}
                    {isAdminSession && workspaceInfo && implementationPipeline?.status !== 'completed' && implementationPipeline?.status !== 'running' && (
                      <Button onClick={handleStartImplementation} variant="outline" className="gap-2" disabled={startingImplementation}>
                        {startingImplementation ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                        Lancer la phase applicative
                      </Button>
                    )}
                    {isAdminSession && implementationPipeline?.status === 'running' && (
                      <div className="flex items-center gap-2 text-primary text-sm font-semibold px-4 py-2 bg-primary/10 rounded-lg border border-primary/20">
                        <span className="h-2 w-2 rounded-full bg-primary animate-ping" />
                        Phase applicative en cours
                      </div>
                    )}
                    <Button onClick={handleRestart} variant="outline" className="gap-2">
                      <Zap className="h-4 w-4" /> Relancer l'analyse
                    </Button>
                  </>
                )}
                {wsStatus === 'running' && (
                  <>
                    <Button onClick={handlePause} variant="outline" className="gap-2">
                      Mettre en pause
                    </Button>
                    <div className="flex items-center gap-2 text-primary text-sm font-semibold px-4 py-2 bg-primary/10 rounded-lg border border-primary/20">
                      <span className="h-2 w-2 rounded-full bg-primary animate-ping" />
                      Analyse en cours...
                    </div>
                  </>
                )}
              </div>
            </div>
          </div>
        </header>

        <main className="flex-1 max-w-7xl mx-auto px-6 py-8 w-full flex flex-col gap-8">
          {(project.status === 'failed' || project.status === 'paused') && (
            <Card className="border-destructive/30 bg-destructive/5">
              <CardHeader className="pb-3">
                <CardTitle className="text-destructive flex items-center gap-2 text-base">
                  <AlertCircle className="h-5 w-5" /> Analyse interrompue
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <p className="text-sm text-muted-foreground">
                  {project.status === 'paused'
                    ? "L'analyse est en pause. Vous pouvez la reprendre plus tard ou la relancer depuis le début."
                    : "L'analyse a été arrêtée car une erreur réelle est survenue pendant l'appel IA. Aucun résultat Mock n'a été généré."}
                </p>
                {persistedWorkflowError && (
                  <pre className="whitespace-pre-wrap rounded-lg border border-destructive/20 bg-background/60 p-4 text-xs text-destructive">
                    {persistedWorkflowError}
                  </pre>
                )}
                <div className="flex flex-wrap gap-3">
                  <Button onClick={handleStart} className="gap-2">
                    <Zap className="h-4 w-4" /> {project.status === 'paused' ? "Reprendre l'analyse" : 'Reprendre depuis checkpoint'}
                  </Button>
                  <Button asChild variant="outline">
                    <Link href="/admin">Configurer les providers IA</Link>
                  </Button>
                </div>
              </CardContent>
            </Card>
          )}

          <div className="flex gap-8 border-b border-border overflow-x-auto scrollbar-none">
            {[
              { id: 'live', label: 'Journal', icon: Terminal },
              { id: 'r1', label: 'Round 1', icon: FileText },
              { id: 'r2', label: 'Round 2 Débat', icon: MessagesSquare },
              { id: 'deliverables', label: 'Round 3 Synthèse', icon: Trophy, disabled: !hasDeliverables && project.status !== 'completed' && (currentRound || 0) < 3 },
            ].map((tab) => {
              const progress = getTabProgress(tab.id as 'live' | 'r1' | 'r2' | 'deliverables');
              return (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id as 'live' | 'r1' | 'r2' | 'deliverables')}
                  disabled={tab.disabled}
                  title={progress === 'complete' ? 'Étape terminée' : progress === 'running' ? 'Étape en cours' : progress === 'error' ? 'Étape bloquée' : 'Étape à venir'}
                  className={cn(
                    'flex items-center gap-2 pb-4 text-sm font-semibold transition-all border-b-2 disabled:opacity-30 disabled:pointer-events-none whitespace-nowrap',
                    activeTab === tab.id ? 'border-primary text-primary' : 'border-transparent text-muted-foreground hover:text-foreground'
                  )}
                >
                  <tab.icon className="h-4 w-4" />
                  {tab.label}
                  <span className="ml-1 inline-flex h-4 w-4 items-center justify-center">
                    {renderTabProgress(progress)}
                  </span>
                </button>
              );
            })}
          </div>

          <div className="flex-1 min-h-[500px]">
            <AnimatePresence mode="wait">{tabContent}</AnimatePresence>
          </div>
        </main>
      </motion.div>

      <button
        onClick={() => setContextPanelOpen(true)}
        className={cn(
          'fixed left-0 top-1/2 z-40 -translate-y-1/2 rounded-r-2xl border border-l-0 border-primary/30 bg-primary text-primary-foreground shadow-2xl shadow-primary/20 transition-transform hover:translate-x-1',
          contextPanelOpen && '-translate-x-full'
        )}
        title="Ouvrir le contexte du projet"
      >
        <span className="flex items-center gap-2 px-3 py-4 [writing-mode:vertical-rl]">
          <span className="text-xs font-bold uppercase tracking-widest">Contexte</span>
          <PanelLeftOpen className="h-4 w-4 rotate-90" />
        </span>
      </button>

      <AnimatePresence>
        {contextPanelOpen && (
          <>
            <motion.div
              className="fixed inset-0 z-40 bg-black/40 backdrop-blur-[2px] xl:hidden"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setContextPanelOpen(false)}
            />
            <motion.aside
              initial={{ x: -760, opacity: 0, scale: 0.96 }}
              animate={{ x: 0, opacity: 1, scale: 1 }}
              exit={{ x: -760, opacity: 0, scale: 0.96 }}
              transition={{ type: 'spring', stiffness: 260, damping: 30 }}
              className="fixed bottom-0 left-0 top-0 z-50 flex w-full max-w-[520px] flex-col border-r border-border bg-background/95 shadow-2xl shadow-black/40 backdrop-blur-xl"
            >
              <div className="flex items-center justify-between border-b border-border/60 p-5">
                <div>
                  <p className="text-[10px] font-bold uppercase tracking-[0.3em] text-primary">Projet live</p>
                  <h2 className="mt-1 text-xl font-bold">Contexte OpenHands</h2>
                </div>
                <Button variant="ghost" size="icon" onClick={() => setContextPanelOpen(false)}>
                  <X className="h-5 w-5" />
                </Button>
              </div>

              <div className="grid min-h-0 flex-1 grid-rows-[1fr_1.15fr] gap-4 overflow-hidden p-4">
                <Card className="flex min-h-0 flex-col overflow-hidden border-border/60 bg-muted/20">
                  <CardHeader className="shrink-0 pb-3">
                    <CardTitle className="flex items-center gap-2 text-base">
                      <FileText className="h-4 w-4 text-primary" />
                      Inputs & données
                    </CardTitle>
                    <CardDescription>
                      Le brief initial et le contexte projet transmis à OpenHands.
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="min-h-0 flex-1 space-y-4 overflow-y-auto pr-3">
                    <div className="rounded-xl border border-dashed border-border bg-background/60 p-4">
                      <p className="mb-2 text-[10px] font-bold uppercase tracking-widest text-muted-foreground">Brief projet</p>
                      <p className="whitespace-pre-wrap text-xs leading-relaxed text-muted-foreground">{project.input_text}</p>
                    </div>
                    <div className="rounded-xl border border-primary/15 bg-primary/5 p-4 text-xs leading-relaxed text-muted-foreground">
                      <Sparkles className="mb-2 h-4 w-4 text-primary" />
                      Les messages envoyés depuis cette page sont injectés dans le contexte réel du projet et peuvent relancer OpenHands.
                    </div>
                    {workspaceInfo && (
                      <div className="space-y-2 rounded-xl border border-border/60 bg-background/60 p-4 text-xs text-muted-foreground">
                        <p><strong>Dossier :</strong> <code>{workspaceInfo.project_dir}</code></p>
                        <p><strong>Racine :</strong> <code>{workspaceInfo.root_path}</code></p>
                        <p><strong>Fichiers :</strong> {Array.isArray(workspaceInfo.files) ? workspaceInfo.files.length : 0}</p>
                      </div>
                    )}
                  </CardContent>
                </Card>

                <Card className="flex min-h-0 flex-col overflow-hidden border-border/60 bg-muted/20">
                  <CardHeader className="shrink-0 pb-3">
                    <CardTitle className="flex items-center gap-2 text-base">
                      <Users className="h-4 w-4 text-primary" />
                      Employés actifs
                    </CardTitle>
                    <CardDescription>
                      Les rôles qui participent au flux de travail du projet.
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="min-h-0 flex-1 space-y-2 overflow-y-auto pr-3">
                    {employeeRoster.map((employee) => {
                      const active = runningAgents[employee.agent];
                      const status = active ? (agentStatuses[employee.agent] || 'Travaille') : (agentStatuses[employee.agent] || 'Disponible');
                      return (
                        <div key={`${employee.agent}-${employee.name}`} className="flex items-center gap-3 rounded-xl border border-border/60 bg-background/60 p-3">
                          <div
                            className={cn(
                              'flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border text-[10px] font-bold',
                              active ? 'border-primary/30 bg-primary/10 text-primary' : 'border-border bg-background text-muted-foreground'
                            )}
                          >
                            {employee.avatar}
                          </div>
                          <div className="min-w-0 flex-1">
                            <p className="truncate text-xs font-bold">{employee.name}</p>
                            <p className="truncate text-[10px] text-muted-foreground">{employee.role}</p>
                          </div>
                          <span
                            className={cn(
                              'whitespace-nowrap rounded-full border px-2 py-0.5 text-[9px]',
                              active
                                ? 'border-primary/20 bg-primary/10 text-primary'
                                : status === 'Terminé'
                                  ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-500'
                                  : status === 'Bloqué'
                                    ? 'border-destructive/20 bg-destructive/10 text-destructive'
                                    : 'border-border bg-background text-muted-foreground'
                            )}
                          >
                            {status}
                          </span>
                        </div>
                      );
                    })}
                  </CardContent>
                </Card>
              </div>
            </motion.aside>
          </>
        )}
      </AnimatePresence>

      <button
        onClick={() => setDeliverablesPanelOpen(true)}
        className={cn(
          'fixed right-0 top-1/2 z-40 -translate-y-1/2 rounded-l-2xl border border-r-0 border-primary/30 bg-primary text-primary-foreground shadow-2xl shadow-primary/20 transition-transform hover:-translate-x-1',
          deliverablesPanelOpen && 'translate-x-full'
        )}
        title="Ouvrir les livrables temps réel"
      >
        <span className="flex items-center gap-2 px-3 py-4 [writing-mode:vertical-rl]">
          <PanelRightOpen className="h-4 w-4 rotate-90" />
          <span className="text-xs font-bold uppercase tracking-widest">Livrables</span>
        </span>
      </button>

      <AnimatePresence>
        {deliverablesPanelOpen && (
          <>
            <motion.div
              className="fixed inset-0 z-40 bg-black/40 backdrop-blur-[2px] xl:hidden"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setDeliverablesPanelOpen(false)}
            />
            <motion.aside
              initial={{ x: 760, opacity: 0, scale: 0.96 }}
              animate={{ x: 0, opacity: 1, scale: 1 }}
              exit={{ x: 760, opacity: 0, scale: 0.96 }}
              transition={{ type: 'spring', stiffness: 260, damping: 30 }}
              className="fixed bottom-0 right-0 top-0 z-50 flex w-full max-w-[760px] flex-col border-l border-border bg-background/95 shadow-2xl shadow-black/40 backdrop-blur-xl"
            >
              <div className="flex items-center justify-between border-b border-border/60 p-5">
                <div>
                  <p className="text-[10px] font-bold uppercase tracking-[0.3em] text-primary">Temps réel</p>
                  <h2 className="mt-1 text-xl font-bold font-display">Livrables du projet</h2>
                </div>
                <Button variant="ghost" size="icon" onClick={() => setDeliverablesPanelOpen(false)}>
                  <X className="h-5 w-5" />
                </Button>
              </div>

              <div className="flex gap-2 overflow-x-auto border-b border-border/60 p-4">
                {[
                  { key: 'cdc', label: 'CDC', icon: BookOpen },
                  { key: 'mcd', label: 'MCD', icon: Database },
                  { key: 'architecture', label: 'Architecture', icon: Layers },
                  { key: 'roadmap', label: 'Roadmap', icon: Calendar },
                  { key: 'notes_synthese', label: 'Synthèse', icon: ClipboardList },
                ].map((item) => (
                  <button
                    key={item.key}
                    onClick={() => setActiveDeliverable(item.key as DeliverableKey)}
                    className={cn(
                      'shrink-0 rounded-full border px-3 py-2 text-xs font-bold transition-colors inline-flex items-center gap-2',
                      activeDeliverable === item.key ? 'border-primary/30 bg-primary/10 text-primary' : 'border-border bg-muted/20 text-muted-foreground hover:text-foreground'
                    )}
                  >
                    <item.icon className="h-3.5 w-3.5" /> {item.label}
                  </button>
                ))}
              </div>

              <div className="border-b border-border/60 px-5 pb-4">
                <div className="flex gap-2 overflow-x-auto">
                  {([
                    { key: 'round1', label: 'Round 1' },
                    { key: 'round2', label: 'Round 2' },
                    { key: 'round3', label: 'Round 3' },
                  ] as { key: ReviewRound; label: string }[]).map((roundOption) => (
                    <button
                      key={roundOption.key}
                      onClick={() => setDeliverableReviewRound(roundOption.key)}
                      className={cn(
                        'shrink-0 rounded-full border px-3 py-2 text-xs font-bold transition-colors',
                        deliverableReviewRound === roundOption.key ? 'border-primary/30 bg-primary/10 text-primary' : 'border-border bg-muted/20 text-muted-foreground hover:text-foreground'
                      )}
                    >
                      {roundOption.label}
                    </button>
                  ))}
                </div>
              </div>

              <div className="flex-1 overflow-y-auto p-5 space-y-5">
                {activeDeliverable === 'mcd' && (
                  <Card className="border-primary/20 bg-primary/5">
                    <CardHeader className="pb-3">
                      <CardTitle className="text-sm flex items-center gap-2">
                        <GitBranch className="h-4 w-4 text-primary" /> Graph Mermaid ERD
                      </CardTitle>
                    </CardHeader>
                    <CardContent>
                      <MermaidDiagram chart={mcdMermaid} emptyMessage={mcdMermaidEmptyMessage} />
                    </CardContent>
                  </Card>
                )}

                <Card className="min-h-[420px] border-border/60">
                  <CardHeader className="border-b border-border/50">
                    <CardTitle className="text-base capitalize flex items-center justify-between gap-3">
                      <span>{activeDeliverable === 'mcd' ? 'MCD / Modèle de données' : activeDeliverable.replace('_', ' ')}</span>
                      <span className="rounded-full border border-primary/20 bg-primary/10 px-3 py-1 text-[10px] font-bold uppercase tracking-widest text-primary">
                        {deliverableRoundLabels[deliverableReviewRound]}
                      </span>
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="p-5 prose prose-slate dark:prose-invert max-w-none text-sm">
                    <div
                      dangerouslySetInnerHTML={{
                        __html: parseMarkdown(
                          activeDeliverable === 'mcd'
                            ? stripMermaidBlocks(selectedDeliverableContent) || '*Description textuelle non générée.*'
                            : selectedDeliverableContent
                        )
                      }}
                    />
                  </CardContent>
                </Card>
              </div>
            </motion.aside>
          </>
        )}
      </AnimatePresence>
    </div>
    </AuthGuard>
  );

}

