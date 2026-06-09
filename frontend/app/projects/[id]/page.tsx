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
  BookOpen,
  Database,
  Layers,
  Calendar,
  ClipboardList
} from 'lucide-react';
import { api } from '../../../lib/api';
import { connectProjectWs, WsEvent } from '../../../lib/websocket';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';

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

export default function ProjectDashboard() {
  const params = useParams();
  const projectId = params.id as string;

  const [project, setProject] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [activeTab, setActiveTab] = useState<'live' | 'r1' | 'r2' | 'deliverables'>('live');
  const [activeDeliverable, setActiveDeliverable] = useState<'cdc' | 'mcd' | 'architecture' | 'roadmap' | 'notes_synthese'>('cdc');

  const [logs, setLogs] = useState<{ text: string; type?: 'info' | 'success' | 'error' | 'system' }[]>([]);
  const [runningAgents, setRunningAgents] = useState<Record<string, boolean>>({});
  const [wsStatus, setWsStatus] = useState<'connecting' | 'running' | 'idle' | 'error'>('idle');

  const wsCleanupRef = useRef<(() => void) | null>(null);
  const logEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (logEndRef.current) logEndRef.current.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  useEffect(() => {
    async function loadProject() {
      try {
        const data = await api.projects.get(projectId);
        setProject(data);
        if (data.status === 'completed') setActiveTab('deliverables');
        else if (data.status === 'running' || data.status === 'pending') startStreaming();
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
    setLogs((prev) => [...prev, { text: 'Connexion au canal de streaming...', type: 'system' }]);

    const cleanup = connectProjectWs(projectId, handleWsEvent, () => {
      setWsStatus('idle');
      refreshProject();
    }, (err) => {
      setWsStatus('error');
      setLogs((prev) => [...prev, { text: 'Connexion interrompue.', type: 'error' }]);
    });
    wsCleanupRef.current = cleanup;
  };

  const refreshProject = async () => {
    try {
      const data = await api.projects.get(projectId);
      setProject(data);
      if (data.status === 'completed') setActiveTab('deliverables');
    } catch (err) {}
  };

  const handleWsEvent = (event: WsEvent) => {
    switch (event.type) {
      case 'round_start':
        setWsStatus('running');
        setLogs((prev) => [...prev, { text: `── ROUND ${event.round} : ${event.message || 'Début'} ──`, type: 'info' }]);
        break;
      case 'agent_start':
        setRunningAgents((prev) => ({ ...prev, [event.agent || '']: true }));
        setLogs((prev) => [...prev, { text: `[Département ${event.agent?.toUpperCase()}] Début de la rédaction...`, type: 'info' }]);
        break;
      case 'agent_complete':
        setRunningAgents((prev) => ({ ...prev, [event.agent || '']: false }));
        setLogs((prev) => [...prev, { text: `[Département ${event.agent?.toUpperCase()}] Rédaction terminée.`, type: 'success' }]);
        break;
      case 'agent_error':
        setRunningAgents((prev) => ({ ...prev, [event.agent || '']: false }));
        setLogs((prev) => [...prev, { text: `[Département ${event.agent?.toUpperCase()}] Erreur : ${event.error}`, type: 'error' }]);
        break;
      case 'workflow_complete':
        setLogs((prev) => [...prev, { text: 'Workflow terminé avec succès !', type: 'success' }]);
        setWsStatus('idle');
        if (event.deliverables) {
          setProject((prev: any) => ({ ...prev, status: 'completed', final_deliverables: event.deliverables }));
          setActiveTab('deliverables');
        }
        break;
      case 'workflow_error':
      case 'error':
        setLogs((prev) => [...prev, { text: `Échec du workflow : ${event.message || event.error}`, type: 'error' }]);
        setWsStatus('error');
        setProject((prev: any) => ({ ...prev, status: 'failed' }));
        break;
    }
  };

  if (loading) return <div className="min-h-screen bg-background flex items-center justify-center"><Loader2 className="h-8 w-8 animate-spin text-primary" /></div>;
  if (error || !project) return (
    <div className="min-h-screen flex items-center justify-center p-6">
      <Card className="max-w-md border-destructive/20">
        <CardHeader><CardTitle className="text-destructive">Erreur</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">{error || 'Session introuvable'}</p>
          <Button asChild variant="outline" className="w-full"><Link href="/">Retour à l'accueil</Link></Button>
        </CardContent>
      </Card>
    </div>
  );

  const deliverables = project.final_deliverables || {};

  return (
    <div className="flex flex-col min-h-screen">
      {/* Page Header */}
      <header className="border-b border-border/60 bg-muted/20">
        <div className="max-w-7xl mx-auto px-6 py-8">
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-6">
            <div className="space-y-2">
              <Link href="/" className="inline-flex items-center text-xs text-muted-foreground hover:text-foreground transition-colors mb-2">
                <ChevronLeft className="mr-1 h-3 w-3" /> Retour
              </Link>
              <h1 className="text-2xl font-bold font-display tracking-tight flex items-center gap-3">
                {project.title}
                <span className={cn(
                  "text-[10px] px-2 py-0.5 rounded-full font-bold uppercase tracking-widest",
                  project.status === 'completed' ? "bg-emerald-500/10 text-emerald-500 border border-emerald-500/20" :
                  project.status === 'running' ? "bg-primary/10 text-primary border border-primary/20 animate-pulse" :
                  project.status === 'failed' ? "bg-destructive/10 text-destructive border border-destructive/20" :
                  "bg-muted text-muted-foreground border border-border"
                )}>
                  {project.status === 'completed' ? 'Terminé' : project.status === 'running' ? 'En cours' : project.status === 'failed' ? 'Échoué' : 'En attente'}
                </span>
              </h1>
              <p className="text-sm text-muted-foreground line-clamp-1 max-w-2xl">{project.input_text}</p>
            </div>
            
            <div className="flex gap-3">
              {(project.status === 'pending' || project.status === 'failed') && wsStatus === 'idle' && (
                <Button onClick={startStreaming} className="gap-2">
                  <Zap className="h-4 w-4" /> Lancer l'Analyse
                </Button>
              )}
              {wsStatus === 'running' && (
                <div className="flex items-center gap-2 text-primary text-sm font-semibold px-4 py-2 bg-primary/10 rounded-lg border border-primary/20">
                  <span className="h-2 w-2 rounded-full bg-primary animate-ping" />
                  Analyse en cours...
                </div>
              )}
            </div>
          </div>
        </div>
      </header>

      {/* Main Workspace */}
      <main className="flex-1 max-w-7xl mx-auto px-6 py-8 w-full flex flex-col gap-8">
        {/* Nav Tabs */}
        <div className="flex gap-8 border-b border-border overflow-x-auto scrollbar-none">
          {[
            { id: 'live', label: 'Journal', icon: Terminal },
            { id: 'r1', label: 'Round 1', icon: FileText },
            { id: 'r2', label: 'Round 2', icon: MessagesSquare },
            { id: 'deliverables', label: 'Livrables', icon: Trophy, disabled: project.status !== 'completed' },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as any)}
              disabled={tab.disabled}
              className={cn(
                "flex items-center gap-2 pb-4 text-sm font-semibold transition-all border-b-2 disabled:opacity-30 disabled:pointer-events-none whitespace-nowrap",
                activeTab === tab.id ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground"
              )}
            >
              <tab.icon className="h-4 w-4" />
              {tab.label}
            </button>
          ))}
        </div>

        {/* Tab Contents */}
        <div className="flex-1 min-h-[500px]">
          <AnimatePresence mode="wait">
            {activeTab === 'live' && (
              <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }} className="grid grid-cols-1 lg:grid-cols-3 gap-8">
                <Card className="lg:col-span-2 bg-black border-border/40 shadow-2xl">
                  <CardHeader className="border-b border-border/40 py-3 flex flex-row items-center justify-between">
                    <CardTitle className="text-xs font-mono text-muted-foreground flex items-center gap-2 uppercase tracking-widest">
                      <Terminal className="h-3.5 w-3.5" /> aia-orchestrator --output-logs
                    </CardTitle>
                    <div className="flex gap-1.5">
                      <div className="h-2.5 w-2.5 rounded-full bg-destructive/50" />
                      <div className="h-2.5 w-2.5 rounded-full bg-amber-500/50" />
                      <div className="h-2.5 w-2.5 rounded-full bg-emerald-500/50" />
                    </div>
                  </CardHeader>
                  <CardContent className="p-0">
                    <div className="h-[450px] overflow-y-auto p-4 font-mono text-[11px] leading-relaxed scrollbar-thin scrollbar-thumb-muted-foreground/20">
                      {logs.map((log, i) => (
                        <div key={i} className={cn(
                          "mb-1.5 flex gap-3",
                          log.type === 'error' ? "text-destructive" :
                          log.type === 'success' ? "text-emerald-500" :
                          log.type === 'system' ? "text-primary" : "text-zinc-400"
                        )}>
                          <span className="opacity-30 shrink-0">[{new Date().toLocaleTimeString()}]</span>
                          <span>{log.text}</span>
                        </div>
                      ))}
                      {logs.length === 0 && <div className="h-full flex flex-col items-center justify-center text-muted-foreground/30 font-sans italic py-20">Attente d'instructions...</div>}
                      <div ref={logEndRef} />
                    </div>
                  </CardContent>
                </Card>

                <div className="space-y-6">
                  <Card>
                    <CardHeader><CardTitle className="text-sm">État des Agents</CardTitle></CardHeader>
                    <CardContent className="space-y-3">
                      {['strategy', 'ux', 'engineering', 'devops'].map((agent) => (
                        <div key={agent} className="flex items-center justify-between p-3 rounded-lg bg-muted/50 border border-border/50">
                          <span className="text-xs font-bold capitalize">{agent}</span>
                          {runningAgents[agent] ? (
                            <span className="text-[10px] bg-primary/10 text-primary px-2 py-0.5 rounded animate-pulse">En cours</span>
                          ) : (
                            <CheckCircle2 className={cn("h-4 w-4", project.status === 'completed' ? "text-emerald-500" : "text-muted-foreground/30")} />
                          )}
                        </div>
                      ))}
                    </CardContent>
                  </Card>
                </div>
              </motion.div>
            )}

            {(activeTab === 'r1' || activeTab === 'r2') && (
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
            )}

            {activeTab === 'deliverables' && (
              <motion.div initial={{ opacity: 0, scale: 0.98 }} animate={{ opacity: 1, scale: 1 }} className="grid grid-cols-1 lg:grid-cols-4 gap-8 items-start">
                <div className="lg:col-span-1 space-y-2">
                  {[
                    { key: 'cdc', label: 'Spécifications', icon: BookOpen },
                    { key: 'mcd', label: 'Modélisation MCD', icon: Database },
                    { key: 'architecture', label: 'Architecture', icon: Layers },
                    { key: 'roadmap', label: 'Roadmap MVP', icon: Calendar },
                    { key: 'notes_synthese', label: 'Synthèse', icon: ClipboardList },
                  ].map((item) => (
                    <button
                      key={item.key}
                      onClick={() => setActiveDeliverable(item.key as any)}
                      className={cn(
                        "w-full flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-semibold transition-all border",
                        activeDeliverable === item.key ? "bg-primary/5 text-primary border-primary/20" : "bg-transparent border-transparent text-muted-foreground hover:bg-muted/50"
                      )}
                    >
                      <item.icon className="h-4 w-4" /> {item.label}
                    </button>
                  ))}
                </div>

                <Card className="lg:col-span-3 min-h-[600px] border-border/60 shadow-xl">
                  <CardHeader className="border-b border-border/40">
                    <CardTitle className="text-xl capitalize flex items-center gap-3">
                      {activeDeliverable === 'cdc' ? <BookOpen className="h-5 w-5 text-primary" /> :
                       activeDeliverable === 'mcd' ? <Database className="h-5 w-5 text-primary" /> :
                       activeDeliverable === 'architecture' ? <Layers className="h-5 w-5 text-primary" /> :
                       activeDeliverable === 'roadmap' ? <Calendar className="h-5 w-5 text-primary" /> :
                       <ClipboardList className="h-5 w-5 text-primary" />}
                      {activeDeliverable.replace('_', ' ')}
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="p-8 prose prose-slate dark:prose-invert max-w-none">
                    <div dangerouslySetInnerHTML={{ __html: parseMarkdown(deliverables[activeDeliverable] || '*Livrable non généré.*') }} />
                  </CardContent>
                </Card>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </main>
    </div>
  );
}
