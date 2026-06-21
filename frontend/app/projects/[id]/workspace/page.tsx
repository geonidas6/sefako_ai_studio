"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { motion, AnimatePresence } from 'framer-motion';
import {
  AlertCircle,
  ArrowLeft,
  Copy,
  ExternalLink,
  FileText,
  Loader2,
  PanelLeftOpen,
  PanelRightOpen,
  RefreshCw,
  Send,
  Sparkles,
  TerminalSquare,
  Users,
  X,
} from 'lucide-react';
import { api } from '../../../../lib/api';
import { connectProjectWs, WsEvent } from '../../../../lib/websocket';
import { AuthGuard } from '@/components/auth-guard';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';

type OpenHandsStatus = {
  enabled: boolean;
  base_url?: string | null;
  alive?: boolean;
  health?: boolean;
  ready?: boolean;
  workspace_dir?: string | null;
  conversation_id?: string | null;
  suggested_url?: string | null;
  embed_url?: string | null;
  notes?: string[];
};

type LogLine = {
  text: string;
  type?: 'info' | 'success' | 'error' | 'system';
  time: string;
};

function normalizeBaseUrl(value: string | undefined | null): string {
  return (value || '').trim().replace(/\/+$/, '');
}

function resolveFallbackUrl(projectId: string): string {
  const publicUrl = normalizeBaseUrl(
    process.env.NEXT_PUBLIC_OPENHANDS_PUBLIC_URL || process.env.NEXT_PUBLIC_OPENHANDS_BASE_URL || ''
  );

  if (!publicUrl) {
    return `https://open-hand-sefako-ai-studio.it-sefako.com/conversations/${projectId}`;
  }

  return `${publicUrl}/conversations/${projectId}`;
}

function withEmbedMode(url: string): string {
  const trimmed = (url || '').trim();
  if (!trimmed) return trimmed;
  if (trimmed.includes('embed=')) return trimmed;
  return `${trimmed}${trimmed.includes('?') ? '&' : '?'}embed=1`;
}

function formatTime() {
  return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

export default function ProjectWorkspacePage() {
  const params = useParams();
  const projectId = params.id as string;
  const logsEndRef = useRef<HTMLDivElement>(null);
  const wsCleanupRef = useRef<(() => void) | null>(null);

  const [project, setProject] = useState<any>(null);
  const [status, setStatus] = useState<OpenHandsStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [statusLoading, setStatusLoading] = useState(true);
  const [error, setError] = useState('');
  const [leftPanelOpen, setLeftPanelOpen] = useState(false);
  const [rightPanelOpen, setRightPanelOpen] = useState(false);
  const [briefInput, setBriefInput] = useState('');
  const [sendingBrief, setSendingBrief] = useState(false);
  const [copyingUrl, setCopyingUrl] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [logs, setLogs] = useState<LogLine[]>([]);

  const fallbackUrl = useMemo(() => resolveFallbackUrl(projectId), [projectId]);
  const targetUrl = withEmbedMode(status?.suggested_url || status?.embed_url || fallbackUrl);
  const workspaceDir = status?.workspace_dir || project?.final_deliverables?.implementation_workspace?.project_dir || '';

  const pushLog = useCallback((text: string, type: LogLine['type'] = 'info') => {
    setLogs((prev) => [...prev.slice(-199), { text, type, time: formatTime() }]);
  }, []);

  const loadData = useCallback(async () => {
    setLoading(true);
    setStatusLoading(true);
    setError('');

    try {
      const [projectData, statusData] = await Promise.all([
        api.projects.get(projectId),
        api.projects.getOpenHandsStatus(projectId),
      ]);

      setProject(projectData);
      setStatus(statusData);

      const baseLogs: LogLine[] = [
        { text: 'Connexion au canal OpenHands...', type: 'system', time: formatTime() },
        ...(statusData?.notes || []).map((note: string) => ({ text: note, type: 'info' as const, time: formatTime() })),
      ];
      if (statusData?.ready) {
        baseLogs.push({ text: 'OpenHands est prêt à recevoir des instructions.', type: 'success', time: formatTime() });
      }
      setLogs(baseLogs);
    } catch (err: any) {
      const message = err?.message || 'Impossible de charger la page OpenHands.';
      setError(message);
      setLogs([{ text: message, type: 'error', time: formatTime() }]);
    } finally {
      setLoading(false);
      setStatusLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    void loadData();
    return () => {
      if (wsCleanupRef.current) wsCleanupRef.current();
    };
  }, [loadData]);

  useEffect(() => {
    if (!projectId) return;

    const cleanup = connectProjectWs(
      projectId,
      (event: WsEvent) => {
        if (event.type === 'workflow_started') {
          pushLog(event.message || 'Analyse lancée côté serveur.', 'system');
          return;
        }
        if (event.type === 'round_start') {
          pushLog(event.message || `Début du round ${event.round ?? '?'}.`, 'system');
          return;
        }
        if (event.type === 'agent_start') {
          pushLog(`[${(event.agent || 'agent').toUpperCase()}] démarrage de la tâche.`, 'info');
          return;
        }
        if (event.type === 'agent_complete') {
          pushLog(`[${(event.agent || 'agent').toUpperCase()}] tâche terminée.`, 'success');
          return;
        }
        if (event.type === 'employee_message' || event.type === 'user_message') {
          pushLog(event.message || event.content || 'Nouveau message reçu.', 'info');
          return;
        }
        if (event.type === 'implementation_status') {
          pushLog(event.message || 'Mise à jour OpenHands reçue.', 'system');
          return;
        }
        if (event.type === 'implementation_complete' || event.type === 'workflow_complete') {
          pushLog(event.message || 'Flux terminé avec succès.', 'success');
          return;
        }
        if (event.type === 'implementation_error' || event.type === 'workflow_error' || event.type === 'agent_error') {
          pushLog(event.error || event.message || 'Une erreur est survenue.', 'error');
        }
      },
      () => pushLog('Canal projet fermé.', 'system'),
      () => pushLog('Impossible de joindre le canal projet.', 'error'),
      { reconnect: true }
    );

    wsCleanupRef.current = cleanup;
    return cleanup;
  }, [projectId, pushLog]);

  useEffect(() => {
    if (logsEndRef.current) {
      logsEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [logs]);

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      await loadData();
      pushLog('Données actualisées.', 'success');
    } finally {
      setRefreshing(false);
    }
  };

  const handleCopyUrl = async () => {
    setCopyingUrl(true);
    try {
      await navigator.clipboard.writeText(targetUrl);
      pushLog('URL OpenHands copiée dans le presse-papiers.', 'success');
    } catch (err: any) {
      pushLog(err?.message || "Impossible de copier l'URL.", 'error');
    } finally {
      setCopyingUrl(false);
    }
  };

  const handleSendBrief = async () => {
    const content = briefInput.trim();
    if (!content) return;
    setSendingBrief(true);
    try {
      const result = await api.projects.sendMessage(projectId, content, 'OpenHands');
      setBriefInput('');
      if (result?.implementation_restart_triggered) {
        pushLog('Brief envoyé à OpenHands et lancement déclenché.', 'success');
      } else {
        pushLog('Brief envoyé dans le contexte du projet OpenHands.', 'system');
      }
    } catch (err: any) {
      pushLog(err?.message || 'Impossible d’envoyer le brief à OpenHands.', 'error');
    } finally {
      setSendingBrief(false);
    }
  };

  const statusBadge = status?.ready ? 'Prêt' : status?.enabled ? 'Connecté' : 'Hors ligne';
  const connectionTone = status?.ready ? 'text-emerald-400' : status?.enabled ? 'text-primary' : 'text-muted-foreground';

  return (
    <AuthGuard>
      <div className="min-h-screen bg-background text-foreground">
        <div className="border-b border-border/60 bg-muted/20">
          <div className="flex w-full max-w-none flex-col gap-5 px-4 py-6 lg:px-6">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="space-y-1">
                <Link href={`/projects/${projectId}`} className="inline-flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground">
                  <ArrowLeft className="h-3.5 w-3.5" /> Retour au projet
                </Link>
                <div className="flex flex-wrap items-center gap-3">
                  <h1 className="text-2xl font-bold tracking-tight">OpenHands workspace</h1>
                  <span className={cn('rounded-full border px-3 py-1 text-xs font-bold uppercase tracking-widest', status?.ready ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-500' : 'border-border bg-background text-muted-foreground')}>
                    {statusBadge}
                  </span>
                  {statusLoading ? <Loader2 className="h-4 w-4 animate-spin text-primary" /> : null}
                </div>
                <p className="max-w-3xl text-sm text-muted-foreground">
                  Le cockpit charge la conversation OpenHands du projet. Si l’embed reste bloqué, ouvre la conversation dans un nouvel onglet.
                </p>
              </div>

              <div className="flex flex-wrap gap-2">
                <Button variant="outline" onClick={handleRefresh} disabled={refreshing} className="gap-2">
                  {refreshing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                  Actualiser
                </Button>
                <Button variant="outline" onClick={handleCopyUrl} disabled={copyingUrl} className="gap-2">
                  <Copy className="h-4 w-4" />
                  Copier l’URL
                </Button>
                <Button asChild className="gap-2">
                  <a href={targetUrl} target="_blank" rel="noreferrer noopener">
                    <ExternalLink className="h-4 w-4" />
                    Ouvrir OpenHands
                  </a>
                </Button>
              </div>
            </div>

            <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-5">
              <Card className="border-border/60 bg-background/60">
                <CardContent className="p-4">
                  <p className="text-[10px] font-bold uppercase tracking-[0.3em] text-muted-foreground">Projet</p>
                  <p className="mt-2 text-lg font-semibold">{project?.title || 'Chargement...'}</p>
                </CardContent>
              </Card>
              <Card className="border-border/60 bg-background/60">
                <CardContent className="p-4">
                  <p className="text-[10px] font-bold uppercase tracking-[0.3em] text-muted-foreground">Conversation</p>
                  <p className="mt-2 truncate text-lg font-semibold">{status?.conversation_id || projectId}</p>
                </CardContent>
              </Card>
              <Card className="border-border/60 bg-background/60">
                <CardContent className="p-4">
                  <p className="text-[10px] font-bold uppercase tracking-[0.3em] text-muted-foreground">Racine</p>
                  <p className="mt-2 truncate text-sm font-semibold">{workspaceDir || 'n/a'}</p>
                </CardContent>
              </Card>
              <Card className="border-border/60 bg-background/60">
                <CardContent className="p-4">
                  <p className="text-[10px] font-bold uppercase tracking-[0.3em] text-muted-foreground">Canal</p>
                  <p className={cn('mt-2 text-lg font-semibold', connectionTone)}>{status?.alive ? 'Alive' : 'Connexion'}</p>
                </CardContent>
              </Card>
              <Card className="border-border/60 bg-background/60">
                <CardContent className="p-4">
                  <p className="text-[10px] font-bold uppercase tracking-[0.3em] text-muted-foreground">État</p>
                  <p className="mt-2 text-lg font-semibold">{status?.health && status?.ready ? 'OK' : 'À vérifier'}</p>
                </CardContent>
              </Card>
            </div>
          </div>
        </div>

        <div className="w-full max-w-none px-4 py-6 lg:px-6">
          <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)]">
            <Card className="overflow-hidden border-border/60 shadow-2xl shadow-black/20">
              <CardHeader className="border-b border-border/60 bg-muted/10">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <CardTitle className="flex items-center gap-2 text-lg">
                      <Sparkles className="h-5 w-5 text-primary" />
                      OpenHands live
                    </CardTitle>
                    <CardDescription>
                      Session locale reliée à la conversation du projet. Le flux principal est dans le cadre central.
                    </CardDescription>
                  </div>
                  <div className="flex items-center gap-2 text-xs text-muted-foreground">
                    {status?.notes?.length ? <span>{status.notes.length} note(s) système</span> : <span>Aucune note système</span>}
                  </div>
                </div>
              </CardHeader>
              <CardContent className="grid min-h-[calc(100vh-300px)] w-full gap-0 p-0 xl:grid-cols-[auto_minmax(0,1fr)_auto]">
                <button
                  type="button"
                  onClick={() => setLeftPanelOpen(true)}
                  className={cn(
                    'fixed left-0 top-1/2 z-40 -translate-y-1/2 rounded-r-2xl border border-l-0 border-primary/30 bg-primary text-primary-foreground shadow-2xl shadow-primary/20 transition-transform hover:translate-x-1',
                    leftPanelOpen && '-translate-x-full'
                  )}
                  title="Ouvrir le contexte du projet"
                >
                  <span className="flex items-center gap-2 px-3 py-4 [writing-mode:vertical-rl]">
                    <span className="text-xs font-bold uppercase tracking-widest">Contexte</span>
                    <PanelLeftOpen className="h-4 w-4 rotate-90" />
                  </span>
                </button>

                <AnimatePresence>
                  {leftPanelOpen && (
                    <>
                      <motion.div
                        className="fixed inset-0 z-40 bg-black/40 backdrop-blur-[2px] xl:hidden"
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        onClick={() => setLeftPanelOpen(false)}
                      />
                      <motion.aside
                        initial={{ x: -720, opacity: 0, scale: 0.98 }}
                        animate={{ x: 0, opacity: 1, scale: 1 }}
                        exit={{ x: -720, opacity: 0, scale: 0.98 }}
                        transition={{ type: 'spring', stiffness: 260, damping: 30 }}
                        className="fixed bottom-0 left-0 top-0 z-50 flex w-full max-w-[540px] flex-col border-r border-border bg-background/95 shadow-2xl shadow-black/40 backdrop-blur-xl"
                      >
                        <div className="flex items-center justify-between border-b border-border/60 p-5">
                          <div>
                            <p className="text-[10px] font-bold uppercase tracking-[0.3em] text-primary">Projet live</p>
                            <h2 className="mt-1 text-xl font-bold">Contexte OpenHands</h2>
                          </div>
                          <Button variant="ghost" size="icon" onClick={() => setLeftPanelOpen(false)}>
                            <X className="h-5 w-5" />
                          </Button>
                        </div>

                        <div className="grid min-h-0 flex-1 grid-rows-[1fr_1.1fr] gap-4 overflow-hidden p-4">
                          <Card className="flex min-h-0 flex-col overflow-hidden border-border/60 bg-muted/20">
                            <CardHeader className="shrink-0 pb-3">
                              <CardTitle className="flex items-center gap-2 text-base">
                                <FileText className="h-4 w-4 text-primary" />
                                Inputs & données
                              </CardTitle>
                              <CardDescription>
                                Le brief projet et les repères transmis à OpenHands.
                              </CardDescription>
                            </CardHeader>
                            <CardContent className="min-h-0 flex-1 space-y-4 overflow-y-auto pr-3">
                              <div className="rounded-xl border border-dashed border-border bg-background/60 p-4">
                                <p className="mb-2 text-[10px] font-bold uppercase tracking-widest text-muted-foreground">Brief projet</p>
                                <p className="whitespace-pre-wrap text-xs leading-relaxed text-muted-foreground">{project?.input_text || 'Chargement du brief...'}</p>
                              </div>
                              <div className="rounded-xl border border-primary/15 bg-primary/5 p-4 text-xs leading-relaxed text-muted-foreground">
                                <Sparkles className="mb-2 h-4 w-4 text-primary" />
                                Les tâches envoyées ici sont injectées dans la conversation OpenHands du projet.
                              </div>
                              <div className="space-y-2 rounded-xl border border-border/60 bg-background/60 p-4 text-xs text-muted-foreground">
                                <p><strong>Dossier :</strong> <code>{workspaceDir || 'n/a'}</code></p>
                                <p><strong>Conversation :</strong> <code>{status?.conversation_id || projectId}</code></p>
                                <p><strong>Source :</strong> <code>{status?.base_url || 'OpenHands public'}</code></p>
                              </div>
                            </CardContent>
                          </Card>

                          <Card className="flex min-h-0 flex-col overflow-hidden border-border/60 bg-muted/20">
                            <CardHeader className="shrink-0 pb-3">
                              <CardTitle className="flex items-center gap-2 text-base">
                                <Users className="h-4 w-4 text-primary" />
                                Envoyer une tâche
                              </CardTitle>
                              <CardDescription>
                                Pousse un brief vers la conversation OpenHands du projet.
                              </CardDescription>
                            </CardHeader>
                            <CardContent className="min-h-0 flex-1 space-y-3 overflow-y-auto pr-3">
                              <textarea
                                value={briefInput}
                                onChange={(event) => setBriefInput(event.target.value)}
                                placeholder="Décris la correction, la feature ou le document à produire..."
                                className="min-h-[220px] w-full resize-none rounded-2xl border border-border bg-background p-4 text-sm outline-none focus:ring-1 focus:ring-primary"
                              />
                              <Button onClick={handleSendBrief} disabled={!briefInput.trim() || sendingBrief} className="w-full gap-2">
                                {sendingBrief ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                                Envoyer au contexte
                              </Button>
                              <p className="rounded-xl border border-dashed border-border bg-background/60 p-4 text-xs leading-relaxed text-muted-foreground">
                                Le backend range aussi cette demande dans le contexte du projet et peut déclencher l’exécution locale OpenHands si le projet est déjà livré.
                              </p>
                            </CardContent>
                          </Card>
                        </div>
                      </motion.aside>
                    </>
                  )}
                </AnimatePresence>

                <div className="min-h-0 border-y border-border/60 bg-background xl:border-y-0 xl:border-r xl:border-border/60">
                  <div className="flex items-center justify-between border-b border-border/60 px-4 py-3">
                    <div>
                      <p className="text-[10px] font-bold uppercase tracking-[0.3em] text-primary">OpenHands workspace</p>
                      <p className="text-sm text-muted-foreground">La conversation du projet s’affiche au centre. Si elle est bloquée, utilise le bouton d’ouverture directe.</p>
                    </div>
                    <span className={cn('inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-bold', status?.ready ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-500' : 'border-border bg-muted/30 text-muted-foreground')}>
                      <span className={cn('h-2 w-2 rounded-full', status?.ready ? 'bg-emerald-500' : 'bg-muted-foreground/40')} />
                      {status?.ready ? 'READY' : 'ATTENTE'}
                    </span>
                  </div>
                  <div className="relative min-h-[calc(100vh-300px)] w-full overflow-hidden bg-[#0a0b10]">
                    {targetUrl ? (
                      <iframe
                        title="OpenHands workspace"
                        src={targetUrl}
                        className="absolute inset-0 h-full w-full border-0 bg-[#0a0b10]"
                        allow="clipboard-read; clipboard-write; fullscreen"
                      />
                    ) : (
                      <div className="flex h-full items-center justify-center p-8 text-center text-muted-foreground">
                        <div className="max-w-md space-y-4">
                          <AlertCircle className="mx-auto h-10 w-10 text-primary" />
                          <p className="text-lg font-semibold text-foreground">Aucune conversation OpenHands n’est disponible.</p>
                          <p className="text-sm">Le service doit être initialisé côté backend avant l’affichage du workspace.</p>
                        </div>
                      </div>
                    )}
                  </div>
                </div>

                <button
                  type="button"
                  onClick={() => setRightPanelOpen(true)}
                  className={cn(
                    'fixed right-0 top-1/2 z-40 -translate-y-1/2 rounded-l-2xl border border-r-0 border-primary/30 bg-primary text-primary-foreground shadow-2xl shadow-primary/20 transition-transform hover:-translate-x-1',
                    rightPanelOpen && 'translate-x-full'
                  )}
                  title="Ouvrir les logs système"
                >
                  <span className="flex items-center gap-2 px-3 py-4 [writing-mode:vertical-rl]">
                    <PanelRightOpen className="h-4 w-4 rotate-90" />
                    <span className="text-xs font-bold uppercase tracking-widest">Logs</span>
                  </span>
                </button>

                <AnimatePresence>
                  {rightPanelOpen && (
                    <>
                      <motion.div
                        className="fixed inset-0 z-40 bg-black/40 backdrop-blur-[2px] xl:hidden"
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        onClick={() => setRightPanelOpen(false)}
                      />
                      <motion.aside
                        initial={{ x: 760, opacity: 0, scale: 0.98 }}
                        animate={{ x: 0, opacity: 1, scale: 1 }}
                        exit={{ x: 760, opacity: 0, scale: 0.98 }}
                        transition={{ type: 'spring', stiffness: 260, damping: 30 }}
                        className="fixed bottom-0 right-0 top-0 z-50 flex w-full max-w-[540px] flex-col border-l border-border bg-background/95 shadow-2xl shadow-black/40 backdrop-blur-xl"
                      >
                        <div className="flex items-center justify-between border-b border-border/60 p-5">
                          <div>
                            <p className="text-[10px] font-bold uppercase tracking-[0.3em] text-primary">OpenHands live</p>
                            <h2 className="mt-1 text-xl font-bold">Contexte & logs</h2>
                          </div>
                          <Button variant="ghost" size="icon" onClick={() => setRightPanelOpen(false)}>
                            <X className="h-5 w-5" />
                          </Button>
                        </div>

                        <div className="grid min-h-0 flex-1 grid-rows-[minmax(0,1.25fr)_minmax(0,0.75fr)] gap-4 overflow-hidden p-4">
                          <Card className="flex min-h-0 flex-col overflow-hidden border-border/60 bg-muted/20">
                            <CardHeader className="shrink-0 pb-3">
                              <CardTitle className="flex items-center gap-2 text-base">
                                <FileText className="h-4 w-4 text-primary" />
                                Contexte du projet
                              </CardTitle>
                              <CardDescription>
                                Le résumé courant transmis à OpenHands.
                              </CardDescription>
                            </CardHeader>
                            <CardContent className="min-h-0 flex-1 space-y-3 overflow-y-auto pr-3 text-sm text-muted-foreground">
                              <div className="rounded-xl border border-border/60 bg-background/60 p-4">
                                <p className="mb-1 text-[10px] font-bold uppercase tracking-widest text-muted-foreground">Projet</p>
                                <p className="text-base font-semibold text-foreground">{project?.title || 'Chargement...'}</p>
                              </div>
                              <div className="rounded-xl border border-border/60 bg-background/60 p-4">
                                <p className="mb-1 text-[10px] font-bold uppercase tracking-widest text-muted-foreground">Statut</p>
                                <p className="font-semibold text-foreground">{status?.ready ? 'OpenHands prêt' : 'OpenHands en attente'}</p>
                              </div>
                              <div className="rounded-xl border border-dashed border-border bg-background/60 p-4">
                                <p className="mb-1 text-[10px] font-bold uppercase tracking-widest text-muted-foreground">Notes système</p>
                                <div className="space-y-2 text-xs leading-relaxed text-muted-foreground">
                                  {(status?.notes || []).length ? status?.notes?.map((note, index) => (
                                    <p key={`${note}-${index}`}>{note}</p>
                                  )) : <p>Aucune note retournée par le backend.</p>}
                                </div>
                              </div>
                            </CardContent>
                          </Card>

                          <Card className="flex min-h-0 flex-col overflow-hidden border-border/60 bg-black/95">
                            <CardHeader className="shrink-0 border-b border-border/40 pb-3">
                              <CardTitle className="flex items-center gap-2 text-base">
                                <TerminalSquare className="h-4 w-4 text-primary" />
                                Logs système
                              </CardTitle>
                              <CardDescription className="text-zinc-400">
                                {status?.health ? 'Canal de service joignable' : 'Surveille les événements du projet en temps réel'}
                              </CardDescription>
                            </CardHeader>
                            <CardContent className="min-h-0 flex-1 overflow-y-auto p-4 font-mono text-xs leading-6 text-zinc-200">
                              <div className="space-y-1">
                                {logs.map((log, index) => (
                                  <div
                                    key={`${log.time}-${index}`}
                                    className={cn(
                                      'flex gap-2',
                                      log.type === 'error' && 'text-rose-400',
                                      log.type === 'success' && 'text-emerald-400',
                                      log.type === 'system' && 'text-primary',
                                      log.type === 'info' && 'text-zinc-300'
                                    )}
                                  >
                                    <span className="shrink-0 opacity-40">[{log.time}]</span>
                                    <span className="whitespace-pre-wrap">{log.text}</span>
                                  </div>
                                ))}
                                {logs.length === 0 ? <p className="text-zinc-500">Aucun log pour le moment.</p> : null}
                                <div ref={logsEndRef} />
                              </div>
                            </CardContent>
                          </Card>
                        </div>
                      </motion.aside>
                    </>
                  )}
                </AnimatePresence>
              </CardContent>
            </Card>
          </div>
        </div>
      </div>
    </AuthGuard>
  );
}
