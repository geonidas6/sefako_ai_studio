'use client';

import { useState, useEffect, useRef } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { api } from '../../../lib/api';
import { connectProjectWs, WsEvent } from '../../../lib/websocket';

// Simple lightweight Markdown to HTML converter to avoid extra dependencies
function parseMarkdown(md: string = ''): string {
  if (!md) return '';

  let html = md
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');

  // Fenced Code blocks
  html = html.replace(/```([\s\S]*?)```/gm, (_, code) => {
    return `<pre><code>${code.trim()}</code></pre>`;
  });

  // Headers
  html = html.replace(/^### (.*$)/gim, '<h3>$1</h3>');
  html = html.replace(/^## (.*$)/gim, '<h2>$1</h2>');
  html = html.replace(/^# (.*$)/gim, '<h1>$1</h1>');

  // Bold
  html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');

  // Inline code
  html = html.replace(/`(.*?)`/g, '<code>$1</code>');

  // Unordered Lists
  html = html.replace(/^\s*[-*]\s+(.*)$/gim, '<li>$1</li>');

  // Wrap consecutive list items in <ul>
  // A simple way is to replace closing and opening list items
  html = html.replace(/(<li>.*<\/li>)/g, '<ul>$1</ul>');
  // Clean up duplicate lists next to each other
  html = html.replace(/<\/ul>\s*<ul>/g, '');

  // Line breaks for paragraphs (split by double newlines)
  const paragraphs = html.split(/\n\n+/);
  html = paragraphs
    .map((p) => {
      p = p.trim();
      if (!p) return '';
      if (p.startsWith('<h') || p.startsWith('<pre') || p.startsWith('<ul') || p.startsWith('<li>')) {
        return p;
      }
      return `<p>${p.replace(/\n/g, '<br />')}</p>`;
    })
    .join('');

  return html;
}

export default function ProjectDashboard() {
  const params = useParams();
  const router = useRouter();
  const projectId = params.id as string;

  const [project, setProject] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [activeTab, setActiveTab] = useState<'live' | 'r1' | 'r2' | 'deliverables'>('live');
  const [activeDeliverable, setActiveDeliverable] = useState<'cdc' | 'mcd' | 'architecture' | 'roadmap' | 'notes'>('cdc');

  // WebSocket / streaming states
  const [logs, setLogs] = useState<string[]>([]);
  const [runningAgents, setRunningAgents] = useState<Record<string, boolean>>({});
  const [completedAgents, setCompletedAgents] = useState<Record<string, { round: number; preview: string }>>({});
  const [currentRound, setCurrentRound] = useState<number>(0);
  const [wsStatus, setWsStatus] = useState<'connecting' | 'running' | 'idle' | 'error'>('idle');

  const wsCleanupRef = useRef<(() => void) | null>(null);

  // Load project initially
  useEffect(() => {
    async function loadProject() {
      try {
        const data = await api.projects.get(projectId);
        setProject(data);

        // If completed, set to deliverables tab by default
        if (data.status === 'completed') {
          setActiveTab('deliverables');
        } else if (data.status === 'running' || data.status === 'pending') {
          // If running or pending, automatically connect WS to listen for logs
          startStreaming();
        }
      } catch (err: any) {
        console.error('Error fetching project:', err);
        setError(err.message || 'Impossible de charger le projet.');
      } finally {
        setLoading(false);
      }
    }

    loadProject();

    return () => {
      if (wsCleanupRef.current) {
        wsCleanupRef.current();
      }
    };
  }, [projectId]);

  const startStreaming = () => {
    if (wsCleanupRef.current) {
      wsCleanupRef.current();
    }
    setWsStatus('connecting');
    setLogs((prev) => [...prev, '[Système] Connexion au canal de streaming...']);

    const cleanup = connectProjectWs(
      projectId,
      (event: WsEvent) => {
        handleWsEvent(event);
      },
      () => {
        setWsStatus('idle');
        // Refresh project data to get final deliverables
        refreshProject();
      },
      (err) => {
        console.error('WS error:', err);
        setWsStatus('error');
        setLogs((prev) => [...prev, '[Erreur] Connexion interrompue.']);
      }
    );

    wsCleanupRef.current = cleanup;
  };

  const refreshProject = async () => {
    try {
      const data = await api.projects.get(projectId);
      setProject(data);
      if (data.status === 'completed') {
        setActiveTab('deliverables');
      }
    } catch (err) {
      console.error('Error refreshing project:', err);
    }
  };

  const handleWsEvent = (event: WsEvent) => {
    const timestamp = event.timestamp ? new Date(event.timestamp).toLocaleTimeString() : '';

    switch (event.type) {
      case 'round_start':
        setCurrentRound(event.round || 0);
        setWsStatus('running');
        setLogs((prev) => [
          ...prev,
          `[${timestamp}] ── ROUND ${event.round} : ${event.message || 'Début'} ──`,
        ]);
        break;

      case 'round_complete':
        setLogs((prev) => [...prev, `[${timestamp}] ✓ Round ${event.round} complété`]);
        setRunningAgents({});
        break;

      case 'agent_start':
        setRunningAgents((prev) => ({ ...prev, [event.agent || '']: true }));
        setLogs((prev) => [
          ...prev,
          `[${timestamp}] [Département ${event.agent?.toUpperCase()}] Début de la rédaction...`,
        ]);
        break;

      case 'agent_complete':
        setRunningAgents((prev) => ({ ...prev, [event.agent || '']: false }));
        setCompletedAgents((prev) => ({
          ...prev,
          [`${event.agent}_r${event.round}`]: {
            round: event.round || 1,
            preview: event.preview || '',
          },
        }));
        setLogs((prev) => [
          ...prev,
          `[${timestamp}] [Département ${event.agent?.toUpperCase()}] ✓ Rédaction terminée. Aperçu : ${
            event.preview ? event.preview.substring(0, 80) + '...' : ''
          }`,
        ]);
        break;

      case 'agent_error':
        setRunningAgents((prev) => ({ ...prev, [event.agent || '']: false }));
        setLogs((prev) => [
          ...prev,
          `[${timestamp}] [Département ${event.agent?.toUpperCase()}] ✗ Erreur : ${event.error}`,
        ]);
        break;

      case 'workflow_complete':
        setLogs((prev) => [...prev, `[${timestamp}] 🎉 Workflow terminé avec succès !`]);
        setWsStatus('idle');
        if (event.deliverables) {
          setProject((prev: any) => ({
            ...prev,
            status: 'completed',
            final_deliverables: event.deliverables,
          }));
          setActiveTab('deliverables');
        }
        break;

      case 'workflow_error':
      case 'error':
        setLogs((prev) => [...prev, `[Erreur] Échec du workflow : ${event.message || event.error}`]);
        setWsStatus('error');
        setProject((prev: any) => ({
          ...prev,
          status: 'failed',
        }));
        break;

      default:
        break;
    }
  };

  const getAgentLabel = (agent: string) => {
    switch (agent) {
      case 'strategy':
        return 'Stratégie & Growth';
      case 'ux':
        return 'Conception & UX';
      case 'engineering':
        return 'Ingénierie & Architecture';
      case 'devops':
        return 'DevOps & Sécurité';
      default:
        return agent;
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-[#05070f] flex items-center justify-center text-muted-foreground">
        Chargement de la session d'analyse...
      </div>
    );
  }

  if (error || !project) {
    return (
      <div className="min-h-screen bg-[#05070f] flex flex-col items-center justify-center p-6 text-center">
        <div className="glass-panel p-8 rounded-xl border border-red-500/20 max-w-md">
          <p className="text-red-400 mb-4">{error || 'Session introuvable'}</p>
          <Link href="/" className="px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-white hover:bg-white/10 transition-all">
            Retour à l'accueil
          </Link>
        </div>
      </div>
    );
  }

  const deliverables = project.final_deliverables || {};

  return (
    <div className="min-h-screen flex flex-col bg-[#05070f] relative overflow-hidden">
      {/* Glows */}
      <div className="absolute top-[-20%] left-[-10%] w-[60%] h-[60%] rounded-full bg-violet-900/5 blur-[150px] pointer-events-none" />
      <div className="absolute bottom-[-20%] right-[-10%] w-[60%] h-[60%] rounded-full bg-cyan-900/5 blur-[150px] pointer-events-none" />

      {/* Header */}
      <header className="w-full border-b border-white/5 bg-[#090b14]/50 backdrop-blur-md sticky top-0 z-20">
        <div className="max-w-7xl mx-auto px-6 py-4 flex justify-between items-center">
          <div className="flex items-center gap-4 min-w-0">
            <Link href="/" className="text-xs text-muted-foreground hover:text-white transition-colors shrink-0">
              ← Accueil
            </Link>
            <span className="text-muted-foreground/30 text-xs shrink-0">/</span>
            <h1 className="text-base font-bold text-white truncate">{project.title}</h1>
            <span
              className={`text-[10px] px-2 py-0.5 rounded-full font-medium shrink-0 ${
                project.status === 'completed'
                  ? 'bg-emerald-950/40 text-emerald-400 border border-emerald-500/20'
                  : project.status === 'running'
                  ? 'bg-violet-950/40 text-violet-400 border border-violet-500/20 animate-pulse'
                  : project.status === 'failed'
                  ? 'bg-red-950/40 text-red-400 border border-red-500/20'
                  : 'bg-yellow-950/40 text-yellow-400 border border-yellow-500/20'
              }`}
            >
              {project.status === 'completed'
                ? 'Terminé'
                : project.status === 'running'
                ? 'En cours'
                : project.status === 'failed'
                ? 'Échoué'
                : 'En attente'}
            </span>
          </div>

          <div className="flex gap-2">
            {(project.status === 'pending' || project.status === 'failed') && wsStatus === 'idle' && (
              <button
                onClick={startStreaming}
                className="text-xs font-semibold bg-gradient-to-r from-violet-600 to-cyan-600 hover:from-violet-500 hover:to-cyan-500 text-white px-4 py-2 rounded-lg transition-all"
              >
                ⚡ Lancer l'Analyse
              </button>
            )}
            {wsStatus === 'running' && (
              <span className="text-xs text-violet-400 flex items-center gap-1.5 font-medium">
                <span className="w-2 h-2 rounded-full bg-violet-500 animate-ping" />
                Débat en direct...
              </span>
            )}
          </div>
        </div>
      </header>

      {/* Workspace Grid */}
      <main className="flex-1 max-w-7xl mx-auto px-6 py-8 w-full z-10 flex flex-col gap-6">
        {/* Project meta summary card */}
        <div className="glass-panel p-5 rounded-2xl border border-white/5 bg-[#090b14]/30">
          <h2 className="text-xs font-bold text-muted-foreground uppercase tracking-widest mb-1.5">Description d'origine</h2>
          <p className="text-xs text-foreground/80 leading-relaxed max-h-24 overflow-y-auto pr-2">
            {project.input_text}
          </p>
        </div>

        {/* Navigation Tabs */}
        <div className="flex border-b border-white/5 gap-4">
          <button
            onClick={() => setActiveTab('live')}
            className={`pb-3 text-sm font-semibold transition-all border-b-2 px-1 ${
              activeTab === 'live'
                ? 'border-violet-500 text-violet-400'
                : 'border-transparent text-muted-foreground hover:text-white'
            }`}
          >
            📋 Journal de l'Orchestrateur
          </button>
          <button
            onClick={() => setActiveTab('r1')}
            className={`pb-3 text-sm font-semibold transition-all border-b-2 px-1 ${
              activeTab === 'r1'
                ? 'border-violet-500 text-violet-400'
                : 'border-transparent text-muted-foreground hover:text-white'
            }`}
          >
            📈 Round 1 : Analyses
          </button>
          <button
            onClick={() => setActiveTab('r2')}
            className={`pb-3 text-sm font-semibold transition-all border-b-2 px-1 ${
              activeTab === 'r2'
                ? 'border-violet-500 text-violet-400'
                : 'border-transparent text-muted-foreground hover:text-white'
            }`}
          >
            💬 Round 2 : Critiques Croisées
          </button>
          <button
            onClick={() => setActiveTab('deliverables')}
            disabled={project.status !== 'completed'}
            className={`pb-3 text-sm font-semibold transition-all border-b-2 px-1 disabled:opacity-40 disabled:pointer-events-none ${
              activeTab === 'deliverables'
                ? 'border-violet-500 text-violet-400'
                : 'border-transparent text-muted-foreground hover:text-white'
            }`}
          >
            🏆 Round 3 : Livrables Synthétisés
          </button>
        </div>

        {/* Tab Contents */}
        <div className="flex-1 min-h-0">
          {/* Tab: Live console logs */}
          {activeTab === 'live' && (
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 h-full items-start">
              {/* Logs area */}
              <div className="glass-panel rounded-2xl border border-white/5 bg-[#03040a]/80 p-5 lg:col-span-2 h-[500px] flex flex-col">
                <div className="flex justify-between items-center mb-3">
                  <h3 className="text-xs font-bold text-white uppercase tracking-wider">Console d'Orchestration</h3>
                  <span className="text-[10px] text-muted-foreground font-mono">WS Status: {wsStatus}</span>
                </div>
                <div className="flex-1 overflow-y-auto font-mono text-[11px] text-zinc-300 space-y-2 p-3 bg-black/40 rounded-xl border border-white/5 scrollbar">
                  {logs.map((log, index) => (
                    <div key={index} className="leading-relaxed border-l-2 border-violet-500/30 pl-3.5 py-0.5">
                      {log}
                    </div>
                  ))}
                  {logs.length === 0 && (
                    <p className="text-muted-foreground text-center py-20 font-sans">
                      Le journal est vide. Cliquez sur "Lancer l'Analyse" pour démarrer le workflow multi-agents.
                    </p>
                  )}
                </div>
              </div>

              {/* Agent Status checklist */}
              <div className="glass-panel p-5 rounded-2xl border border-white/5 bg-[#090b14]/50 space-y-6">
                <div>
                  <h3 className="text-xs font-bold text-white uppercase tracking-wider mb-3">État des Agents</h3>
                  <div className="space-y-3">
                    {['strategy', 'ux', 'engineering', 'devops'].map((agent) => {
                      const isRunning = runningAgents[agent];
                      const isDoneR1 = !!completedAgents[`${agent}_r1`];
                      const isDoneR2 = !!completedAgents[`${agent}_r2`];

                      return (
                        <div key={agent} className="p-3 rounded-xl bg-white/5 border border-white/5 flex items-center justify-between">
                          <span className="text-xs font-bold text-white">{getAgentLabel(agent)}</span>
                          <div className="flex items-center gap-2">
                            {isRunning ? (
                              <span className="text-[10px] bg-violet-950/40 text-violet-400 px-2 py-0.5 rounded border border-violet-500/20 animate-pulse">
                                Rédige...
                              </span>
                            ) : isDoneR2 ? (
                              <span className="text-[10px] bg-emerald-950/40 text-emerald-400 px-2 py-0.5 rounded border border-emerald-500/20">
                                Prêt (R2)
                              </span>
                            ) : isDoneR1 ? (
                              <span className="text-[10px] bg-blue-950/40 text-blue-400 px-2 py-0.5 rounded border border-blue-500/20">
                                Prêt (R1)
                              </span>
                            ) : (
                              <span className="text-[10px] bg-zinc-900 text-zinc-500 px-2 py-0.5 rounded border border-zinc-800">
                                Inactif
                              </span>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>

                <div className="p-4 bg-white/5 rounded-xl border border-white/5 text-xs text-muted-foreground leading-relaxed">
                  📊 <strong>En direct :</strong> Le journal montre les étapes d'exécution de LangGraph. Lorsque la synthèse est générée, l'application bascule automatiquement sur les livrables finaux.
                </div>
              </div>
            </div>
          )}

          {/* Tab: Round 1 (Analyses) */}
          {activeTab === 'r1' && (
            <div className="space-y-6">
              <div className="text-sm text-muted-foreground">
                Voici les livrables bruts rédigés par chaque département au cours du premier round.
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                {[
                  { key: 'strategy', title: '📈 Département Stratégie', content: project.strategy_r1 },
                  { key: 'ux', title: '🎨 Département UX', content: project.ux_r1 },
                  { key: 'engineering', title: '⚙️ Département Ingénierie', content: project.engineering_r1 },
                  { key: 'devops', title: '🛡️ Département DevOps', content: project.devops_r1 },
                ].map((sec) => (
                  <div key={sec.key} className="glass-panel p-5 rounded-xl border border-white/5 h-[350px] flex flex-col bg-[#090b14]/50">
                    <h3 className="text-sm font-bold text-white mb-3">{sec.title}</h3>
                    <div
                      className="flex-1 overflow-y-auto text-xs text-muted-foreground space-y-2 prose pr-2 scrollbar"
                      dangerouslySetInnerHTML={{ __html: parseMarkdown(sec.content || '_Aucun livrable disponible pour ce round._') }}
                    />
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Tab: Round 2 (Critiques) */}
          {activeTab === 'r2' && (
            <div className="space-y-6">
              <div className="text-sm text-muted-foreground">
                Chaque agent s'est vu présenter le travail de ses confrères. Voici leurs critiques croisées et propositions de compromis.
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                {[
                  { key: 'strategy', title: '📈 Critique Stratégie', content: project.critiques?.strategy },
                  { key: 'ux', title: '🎨 Critique UX', content: project.critiques?.ux },
                  { key: 'engineering', title: '⚙️ Critique Ingénierie', content: project.critiques?.engineering },
                  { key: 'devops', title: '🛡️ Critique DevOps', content: project.critiques?.devops },
                ].map((sec) => (
                  <div key={sec.key} className="glass-panel p-5 rounded-xl border border-white/5 h-[350px] flex flex-col bg-[#090b14]/50">
                    <h3 className="text-sm font-bold text-white mb-3">{sec.title}</h3>
                    <div
                      className="flex-1 overflow-y-auto text-xs text-muted-foreground space-y-2 prose pr-2 scrollbar"
                      dangerouslySetInnerHTML={{ __html: parseMarkdown(sec.content || '_Aucune critique disponible pour ce round._') }}
                    />
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Tab: Deliverables (Completed) */}
          {activeTab === 'deliverables' && (
            <div className="grid grid-cols-1 lg:grid-cols-4 gap-6 items-start">
              {/* Deliverable selector list */}
              <div className="glass-panel p-4 rounded-xl border border-white/5 space-y-2 bg-[#090b14]/50">
                <h3 className="text-xs font-bold text-white uppercase tracking-wider mb-3 px-2">Spécifications</h3>
                {[
                  { key: 'cdc', label: '📖 Cahier des Charges' },
                  { key: 'mcd', label: '📊 Modélisation MCD' },
                  { key: 'architecture', label: '🏗️ Architecture Technique' },
                  { key: 'roadmap', label: '📅 Roadmap MVP' },
                  { key: 'notes', label: '📝 Notes de Synthèse' },
                ].map((item) => (
                  <button
                    key={item.key}
                    onClick={() => setActiveDeliverable(item.key as any)}
                    className={`w-full text-left text-xs font-semibold px-3 py-2.5 rounded-lg transition-all border flex justify-between items-center ${
                      activeDeliverable === item.key
                        ? 'bg-violet-600/10 text-violet-400 border-violet-500/30'
                        : 'border-transparent text-muted-foreground hover:bg-white/5 hover:text-white'
                    }`}
                  >
                    <span>{item.label}</span>
                    <span>→</span>
                  </button>
                ))}
              </div>

              {/* Deliverable preview content panel */}
              <div className="glass-panel p-6 rounded-2xl border border-white/5 lg:col-span-3 min-h-[500px] bg-[#090b14]/20 flex flex-col">
                <div className="flex justify-between items-center border-b border-white/5 pb-4 mb-4">
                  <h3 className="text-lg font-bold text-white font-display uppercase tracking-wide">
                    {activeDeliverable === 'cdc' && '📖 Cahier des Charges'}
                    {activeDeliverable === 'mcd' && '📊 Modélisation Conceptuelle des Données'}
                    {activeDeliverable === 'architecture' && '🏗️ Architecture Technique'}
                    {activeDeliverable === 'roadmap' && '📅 Roadmap MVP'}
                    {activeDeliverable === 'notes' && '📝 Notes de Synthèse & Arbitrage'}
                  </h3>
                </div>

                <div className="flex-1 prose text-muted-foreground text-sm max-w-none">
                  {activeDeliverable === 'cdc' && (
                    <div dangerouslySetInnerHTML={{ __html: parseMarkdown(deliverables.cdc) }} />
                  )}
                  {activeDeliverable === 'mcd' && (
                    <div dangerouslySetInnerHTML={{ __html: parseMarkdown(deliverables.mcd) }} />
                  )}
                  {activeDeliverable === 'architecture' && (
                    <div dangerouslySetInnerHTML={{ __html: parseMarkdown(deliverables.architecture) }} />
                  )}
                  {activeDeliverable === 'roadmap' && (
                    <div dangerouslySetInnerHTML={{ __html: parseMarkdown(deliverables.roadmap) }} />
                  )}
                  {activeDeliverable === 'notes' && (
                    <div dangerouslySetInnerHTML={{ __html: parseMarkdown(deliverables.notes_synthese) }} />
                  )}
                  {!deliverables[activeDeliverable === 'notes' ? 'notes_synthese' : activeDeliverable] && (
                    <p className="text-xs italic text-muted-foreground">Ce livrable est vide.</p>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
