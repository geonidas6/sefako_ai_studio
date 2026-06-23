"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { motion, AnimatePresence } from 'framer-motion';
import {
  ArrowLeft,
  Copy,
  ExternalLink,
  FileText,
  FolderTree,
  Loader2,
  RefreshCw,
  Sparkles,
  TerminalSquare,
  X,
} from 'lucide-react';
import { api } from '../../../../lib/api';
import { connectProjectWs, WsEvent } from '../../../../lib/websocket';
import { AuthGuard } from '@/components/auth-guard';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';

type LogLine = {
  text: string;
  type?: 'info' | 'success' | 'error' | 'system';
  time: string;
};

function normalizeBaseUrl(value: string | undefined | null): string {
  return (value || '').trim().replace(/\/+$/, '');
}

function formatTime() {
  return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function extractWorkspace(project: any) {
  return project?.final_deliverables?.implementation_workspace || project?.final_deliverables?.implementation_pipeline || {};
}

export default function ProjectWorkspacePage() {
  const params = useParams();
  const projectId = params.id as string;
  const logsEndRef = useRef<HTMLDivElement>(null);
  const wsCleanupRef = useRef<(() => void) | null>(null);

  const [project, setProject] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [copyingUrl, setCopyingUrl] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [logs, setLogs] = useState<LogLine[]>([]);
  const [logsOpen, setLogsOpen] = useState(false);

  const ideBase = useMemo(
    () => normalizeBaseUrl(process.env.NEXT_PUBLIC_IDE_PUBLIC_URL || 'https://ide.it-sefako.com'),
    []
  );

  const pushLog = useCallback((text: string, type: LogLine['type'] = 'info') => {
    setLogs((prev) => [...prev.slice(-199), { text, type, time: formatTime() }]);
  }, []);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError('');

    try {
      const projectData = await api.projects.get(projectId);
      setProject(projectData);

      setLogs([
        { text: 'Connexion au flux du projet...', type: 'system', time: formatTime() },
        { text: 'L’éditeur web est l’espace de travail principal pour le code et les fichiers .md.', type: 'info', time: formatTime() },
      ]);
    } catch (err: any) {
      const message = err?.message || 'Impossible de charger le workspace du projet.';
      setError(message);
      setLogs([{ text: message, type: 'error', time: formatTime() }]);
    } finally {
      setLoading(false);
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
          pushLog(event.message || 'Mise à jour du workspace reçue.', 'system');
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

  const workspace = extractWorkspace(project);
  const workspaceDir = workspace?.project_dir || '';
  const workspaceFiles: string[] = Array.isArray(workspace?.files) ? workspace.files : [];
  const markdownFiles = workspaceFiles.filter((file) => file.toLowerCase().endsWith('.md'));
  const editorUrl = workspaceDir ? `${ideBase}/?folder=${encodeURIComponent(workspaceDir)}` : ideBase;
  const projectStatus = String(project?.status || '').toLowerCase();
  const projectStatusLabel = (() => {
    switch (projectStatus) {
      case 'completed': return 'Projet terminé';
      case 'running': return 'Projet en cours';
      case 'paused': return 'Projet en pause';
      case 'failed': return 'Projet en erreur';
      default: return 'Projet en attente';
    }
  })();
  const projectStatusTone = (() => {
    switch (projectStatus) {
      case 'completed': return 'border-emerald-500/20 bg-emerald-500/10 text-emerald-500';
      case 'running': return 'border-primary/20 bg-primary/10 text-primary';
      case 'failed': return 'border-destructive/20 bg-destructive/10 text-destructive';
      case 'paused': return 'border-amber-500/20 bg-amber-500/10 text-amber-500';
      default: return 'border-border bg-background text-muted-foreground';
    }
  })();

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
      await navigator.clipboard.writeText(editorUrl);
      pushLog("URL de l'éditeur copiée dans le presse-papiers.", 'success');
    } catch (err: any) {
      pushLog(err?.message || "Impossible de copier l'URL.", 'error');
    } finally {
      setCopyingUrl(false);
    }
  };

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
                  <h1 className="text-2xl font-bold tracking-tight">Workspace projet</h1>
                  <span className={cn('rounded-full border px-3 py-1 text-xs font-bold uppercase tracking-widest', projectStatusTone)}>
                    {projectStatusLabel}
                  </span>
                  <span className="rounded-full border border-primary/20 bg-primary/10 px-3 py-1 text-xs font-bold uppercase tracking-widest text-primary">
                    {workspaceDir ? 'Éditeur prêt' : 'Aucun workspace'}
                  </span>
                </div>
                <p className="max-w-3xl text-sm text-muted-foreground">
                  Les documents Markdown sont créés dans le dossier projet. Ouvre ensuite ce workspace directement dans l’éditeur web.
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
                <Button asChild className="gap-2" disabled={!workspaceDir}>
                  <a href={editorUrl} target="_blank" rel="noreferrer noopener">
                    <ExternalLink className="h-4 w-4" />
                    Ouvrir l’éditeur
                  </a>
                </Button>
              </div>
            </div>

            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
              <Card className="border-border/60 bg-background/60">
                <CardContent className="p-4">
                  <p className="text-[10px] font-bold uppercase tracking-[0.3em] text-muted-foreground">Projet</p>
                  <p className="mt-2 text-lg font-semibold">{project?.title || 'Chargement...'}</p>
                </CardContent>
              </Card>
              <Card className="border-border/60 bg-background/60">
                <CardContent className="p-4">
                  <p className="text-[10px] font-bold uppercase tracking-[0.3em] text-muted-foreground">Dossier</p>
                  <p className="mt-2 truncate text-sm font-semibold">{workspaceDir || 'n/a'}</p>
                </CardContent>
              </Card>
              <Card className="border-border/60 bg-background/60">
                <CardContent className="p-4">
                  <p className="text-[10px] font-bold uppercase tracking-[0.3em] text-muted-foreground">Markdown</p>
                  <p className="mt-2 text-lg font-semibold">{markdownFiles.length}</p>
                </CardContent>
              </Card>
              <Card className="border-border/60 bg-background/60">
                <CardContent className="p-4">
                  <p className="text-[10px] font-bold uppercase tracking-[0.3em] text-muted-foreground">Éditeur</p>
                  <p className="mt-2 truncate text-sm font-semibold">{ideBase || 'n/a'}</p>
                </CardContent>
              </Card>
            </div>
          </div>
        </div>

        <div className="w-full max-w-none px-4 py-6 lg:px-6">
          <div className="grid gap-6 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)]">
            <Card className="overflow-hidden border-border/60 shadow-2xl shadow-black/20">
              <CardHeader className="border-b border-border/60 bg-muted/10">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <CardTitle className="flex items-center gap-2 text-lg">
                      <Sparkles className="h-5 w-5 text-primary" />
                      Espace de travail
                    </CardTitle>
                    <CardDescription>
                      Les fichiers générés dans le dossier projet sont visibles ici avant ouverture dans l’éditeur.
                    </CardDescription>
                  </div>
                  <span className={cn('inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-bold', workspaceDir ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-500' : 'border-border bg-muted/30 text-muted-foreground')}>
                    <span className={cn('h-2 w-2 rounded-full', workspaceDir ? 'bg-emerald-500' : 'bg-muted-foreground/40')} />
                    {workspaceDir ? 'READY' : 'ATTENTE'}
                  </span>
                </div>
              </CardHeader>
              <CardContent className="space-y-6 p-6">
                <div className="grid gap-4 md:grid-cols-3">
                  <Card className="border-border/60 bg-background/60">
                    <CardContent className="p-4">
                      <p className="text-[10px] font-bold uppercase tracking-[0.3em] text-muted-foreground">Statut</p>
                      <p className="mt-2 text-lg font-semibold">{projectStatusLabel}</p>
                    </CardContent>
                  </Card>
                  <Card className="border-border/60 bg-background/60">
                    <CardContent className="p-4">
                      <p className="text-[10px] font-bold uppercase tracking-[0.3em] text-muted-foreground">Fichiers</p>
                      <p className="mt-2 text-lg font-semibold">{workspaceFiles.length}</p>
                    </CardContent>
                  </Card>
                  <Card className="border-border/60 bg-background/60">
                    <CardContent className="p-4">
                      <p className="text-[10px] font-bold uppercase tracking-[0.3em] text-muted-foreground">Dernier état</p>
                      <p className="mt-2 text-sm font-semibold text-muted-foreground">
                        {loading ? 'Chargement...' : (workspaceDir ? 'Workspace prêt à ouvrir' : 'Workspace non encore initialisé')}
                      </p>
                    </CardContent>
                  </Card>
                </div>

                <div className="space-y-3">
                  <div className="flex items-center gap-2">
                    <FileText className="h-4 w-4 text-primary" />
                    <h2 className="text-base font-semibold">Fichiers Markdown</h2>
                  </div>
                  <div className="rounded-2xl border border-border/60 bg-background/60 p-4">
                    {markdownFiles.length ? (
                      <div className="flex flex-wrap gap-2">
                        {markdownFiles.map((file) => (
                          <span key={file} className="inline-flex items-center gap-2 rounded-full border border-border/60 bg-muted/20 px-3 py-1 text-xs text-muted-foreground">
                            <FileText className="h-3.5 w-3.5 text-primary" />
                            {file}
                          </span>
                        ))}
                      </div>
                    ) : (
                      <p className="text-sm text-muted-foreground">
                        Aucun fichier Markdown n’a encore été généré dans ce workspace.
                      </p>
                    )}
                  </div>
                </div>

                <div className="rounded-2xl border border-primary/15 bg-primary/5 p-4">
                  <p className="text-[10px] font-bold uppercase tracking-[0.3em] text-primary">Action recommandée</p>
                  <p className="mt-2 text-sm text-muted-foreground">
                    Ouvre le projet dans l’éditeur web pour modifier les fichiers directement dans <code>{workspaceDir || '/projects'}</code>.
                  </p>
                </div>

                {error ? (
                  <div className="rounded-2xl border border-destructive/20 bg-destructive/10 p-4 text-sm text-destructive">
                    {error}
                  </div>
                ) : null}
              </CardContent>
            </Card>

            <Card className="overflow-hidden border-border/60 shadow-2xl shadow-black/20">
              <CardHeader className="border-b border-border/60 bg-muted/10">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <CardTitle className="flex items-center gap-2 text-lg">
                      <TerminalSquare className="h-5 w-5 text-primary" />
                      Journal du projet
                    </CardTitle>
                    <CardDescription>
                      Les événements de workflow continuent d’arriver ici pendant la phase de génération.
                    </CardDescription>
                  </div>
                  <Button variant="ghost" size="icon" onClick={() => setLogsOpen((value) => !value)} title={logsOpen ? 'Réduire' : 'Étendre'}>
                    <X className={cn('h-5 w-5 transition-transform', logsOpen ? 'rotate-45' : 'rotate-0')} />
                  </Button>
                </div>
              </CardHeader>
              <CardContent className="space-y-4 p-0">
                <div className="max-h-[540px] overflow-y-auto p-4">
                  <div className="space-y-2 font-mono text-xs leading-6 text-zinc-200">
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
                </div>

                <AnimatePresence>
                  {logsOpen && (
                    <motion.div
                      initial={{ opacity: 0, height: 0 }}
                      animate={{ opacity: 1, height: 'auto' }}
                      exit={{ opacity: 0, height: 0 }}
                      className="border-t border-border/60 bg-muted/10 p-4 text-sm text-muted-foreground"
                    >
                      <p>
                        Le conteneur IDE écoute le workspace projet. Tu peux ouvrir le dossier directement avec le bouton
                        <span className="font-semibold text-foreground"> Ouvrir l’éditeur</span>.
                      </p>
                    </motion.div>
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
