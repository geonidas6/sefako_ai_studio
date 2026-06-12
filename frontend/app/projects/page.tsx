'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { motion } from 'framer-motion';
import {
  Calendar,
  Clock3,
  ExternalLink,
  FileText,
  Filter,
  Plus,
  Search,
  Trash2,
} from 'lucide-react';
import { api } from '../../lib/api';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';

type ProjectStatus = 'all' | 'pending' | 'running' | 'paused' | 'completed' | 'failed';

interface Project {
  id: string;
  title: string;
  input_text: string;
  status: string;
  created_at: string;
  completed_at?: string | null;
}

const statusLabels: Record<string, string> = {
  pending: 'En attente',
  running: 'En cours',
  paused: 'En pause',
  completed: 'Terminé',
  failed: 'Échoué',
};

const statusClasses: Record<string, string> = {
  pending: 'bg-muted text-muted-foreground border-border',
  running: 'bg-primary/10 text-primary border-primary/20 animate-pulse',
  paused: 'bg-amber-500/10 text-amber-500 border-amber-500/20',
  completed: 'bg-emerald-500/10 text-emerald-500 border-emerald-500/20',
  failed: 'bg-destructive/10 text-destructive border-destructive/20',
};

export default function ProjectsPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState<ProjectStatus>('all');

  useEffect(() => {
    loadProjects();
  }, []);

  const loadProjects = async () => {
    setError('');
    try {
      const data = await api.projects.list();
      setProjects(data);
    } catch (err: any) {
      setError(err.message || 'Impossible de charger les projets.');
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (project: Project) => {
    if (!confirm(`Supprimer le projet "${project.title}" ?`)) return;
    try {
      await api.projects.delete(project.id);
      setProjects((prev) => prev.filter((item) => item.id !== project.id));
    } catch (err: any) {
      alert(err.message || 'Erreur lors de la suppression du projet.');
    }
  };

  const filteredProjects = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return projects.filter((project) => {
      const matchesStatus = status === 'all' || project.status === status;
      const matchesQuery = !normalizedQuery
        || project.title.toLowerCase().includes(normalizedQuery)
        || project.input_text.toLowerCase().includes(normalizedQuery);
      return matchesStatus && matchesQuery;
    });
  }, [projects, query, status]);

  const statusCounts = useMemo(() => {
    return projects.reduce<Record<string, number>>((acc, project) => {
      acc[project.status] = (acc[project.status] || 0) + 1;
      return acc;
    }, {});
  }, [projects]);

  const filters: { key: ProjectStatus; label: string }[] = [
    { key: 'all', label: 'Tous' },
    { key: 'running', label: 'En cours' },
    { key: 'paused', label: 'En pause' },
    { key: 'completed', label: 'Terminés' },
    { key: 'failed', label: 'Échoués' },
    { key: 'pending', label: 'En attente' },
  ];

  return (
    <div className="max-w-7xl mx-auto px-6 py-12 md:py-20 space-y-10">
      <div className="flex flex-col lg:flex-row lg:items-end justify-between gap-6">
        <div className="space-y-3">
          <div className="inline-flex items-center gap-2 rounded-full border border-primary/20 bg-primary/5 px-3 py-1 text-xs font-semibold text-primary">
            <FileText className="h-3.5 w-3.5" /> Tableau de bord projets
          </div>
          <div>
            <h1 className="text-3xl md:text-4xl font-bold font-display tracking-tight">Tous les projets</h1>
            <p className="text-muted-foreground mt-2 max-w-2xl">
              Retrouvez les analyses en cours, en pause, terminées ou échouées. C'est le cockpit pour reprendre le travail plus tard.
            </p>
          </div>
        </div>
        <Button asChild className="h-11 px-5 gap-2">
          <Link href="/studio">
            <Plus className="h-4 w-4" /> Nouveau projet
          </Link>
        </Button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        {[
          { label: 'Total', value: projects.length, className: 'text-foreground' },
          { label: 'En cours', value: statusCounts.running || 0, className: 'text-primary' },
          { label: 'En pause', value: statusCounts.paused || 0, className: 'text-amber-500' },
          { label: 'Terminés', value: statusCounts.completed || 0, className: 'text-emerald-500' },
        ].map((item) => (
          <Card key={item.label} className="bg-muted/20 border-border/60">
            <CardContent className="p-5">
              <p className="text-xs text-muted-foreground font-semibold uppercase tracking-wider">{item.label}</p>
              <p className={cn('text-3xl font-bold font-display mt-2', item.className)}>{item.value}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      <Card className="border-border/60">
        <CardContent className="p-4 flex flex-col lg:flex-row gap-4 lg:items-center justify-between">
          <div className="relative flex-1 max-w-xl">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Rechercher par titre ou description..."
              className="pl-9 h-10"
            />
          </div>
          <div className="flex items-center gap-2 overflow-x-auto pb-1 lg:pb-0">
            <Filter className="h-4 w-4 text-muted-foreground shrink-0" />
            {filters.map((filter) => (
              <button
                key={filter.key}
                onClick={() => setStatus(filter.key)}
                className={cn(
                  'rounded-full border px-3 py-1.5 text-xs font-semibold whitespace-nowrap transition-colors',
                  status === filter.key
                    ? 'border-primary/30 bg-primary/10 text-primary'
                    : 'border-border bg-background text-muted-foreground hover:text-foreground'
                )}
              >
                {filter.label}
              </button>
            ))}
          </div>
        </CardContent>
      </Card>

      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
          {[1, 2, 3, 4, 5, 6].map((item) => <div key={item} className="h-56 rounded-xl bg-muted animate-pulse" />)}
        </div>
      ) : error ? (
        <Card className="border-destructive/20 bg-destructive/5 text-destructive p-8 text-center">
          {error}
        </Card>
      ) : filteredProjects.length === 0 ? (
        <Card className="border-dashed bg-muted/20 p-12 text-center">
          <div className="mx-auto max-w-sm space-y-4">
            <div className="mx-auto h-12 w-12 rounded-full bg-muted flex items-center justify-center">
              <Search className="h-5 w-5 text-muted-foreground" />
            </div>
            <div>
              <p className="font-semibold">Aucun projet trouvé</p>
              <p className="text-sm text-muted-foreground mt-1">Ajuste la recherche ou crée une nouvelle analyse.</p>
            </div>
            <Button asChild>
              <Link href="/studio">Créer un projet</Link>
            </Button>
          </div>
        </Card>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
          {filteredProjects.map((project, index) => (
            <motion.div
              key={project.id}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.25, delay: index * 0.03 }}
            >
              <Card className="h-full border-border/60 hover:border-primary/30 hover:shadow-xl hover:shadow-primary/5 transition-all overflow-hidden group">
                <CardHeader className="pb-3">
                  <div className="flex items-center justify-between gap-3 mb-2">
                    <span className={cn(
                      'text-[10px] uppercase font-bold tracking-widest px-2 py-0.5 rounded-full border',
                      statusClasses[project.status] || statusClasses.pending
                    )}>
                      {statusLabels[project.status] || project.status}
                    </span>
                    <span className="text-[10px] text-muted-foreground inline-flex items-center gap-1">
                      <Calendar className="h-3 w-3" /> {new Date(project.created_at).toLocaleDateString('fr-FR')}
                    </span>
                  </div>
                  <CardTitle className="line-clamp-1 text-lg group-hover:text-primary transition-colors">
                    {project.title}
                  </CardTitle>
                  <CardDescription className="line-clamp-3 pt-2 text-xs leading-relaxed">
                    {project.input_text}
                  </CardDescription>
                </CardHeader>
                <CardContent className="pt-0 space-y-4">
                  <div className="flex items-center justify-between text-[10px] text-muted-foreground border-t border-border/50 pt-4">
                    <span className="inline-flex items-center gap-1">
                      <Clock3 className="h-3 w-3" /> {project.completed_at ? 'Finalisé' : 'Non finalisé'}
                    </span>
                    <span className="font-mono">{project.id.slice(0, 8)}</span>
                  </div>
                  <div className="flex items-center justify-between gap-3">
                    <Button asChild size="sm" className="flex-1 gap-2">
                      <Link href={`/projects/${project.id}`}>
                        Ouvrir <ExternalLink className="h-3.5 w-3.5" />
                      </Link>
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => handleDelete(project)}
                      className="text-muted-foreground hover:text-destructive hover:bg-destructive/10"
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </CardContent>
              </Card>
            </motion.div>
          ))}
        </div>
      )}
    </div>
  );
}
