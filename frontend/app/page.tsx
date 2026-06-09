'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { motion } from 'framer-motion';
import { 
  TrendingUp, 
  Palette, 
  Settings2, 
  ShieldCheck, 
  ArrowRight, 
  Plus, 
  History,
  Trash2,
  ExternalLink,
  ChevronRight
} from 'lucide-react';
import { api } from '../lib/api';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';

interface Project {
  id: string;
  title: string;
  input_text: string;
  status: string;
  created_at: string;
}

export default function LandingPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    async function loadProjects() {
      try {
        const data = await api.projects.list();
        setProjects(data);
      } catch (err: any) {
        console.error('Failed to load projects:', err);
        setError(err.message || 'Impossible de charger les projets.');
      } finally {
        setLoading(false);
      }
    }
    loadProjects();
  }, []);

  const handleDelete = async (id: string, e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (!confirm('Êtes-vous sûr de vouloir supprimer ce projet ?')) return;
    try {
      await api.projects.delete(id);
      setProjects(projects.filter((p) => p.id !== id));
    } catch (err: any) {
      alert(err.message || 'Erreur lors de la suppression');
    }
  };

  const departments = [
    {
      name: 'Stratégie & Growth',
      icon: TrendingUp,
      desc: 'Analyse de viabilité, KPIs de succès, modélisation business et positionnement concurrentiel.',
      color: 'text-pink-500'
    },
    {
      name: 'Conception & UX',
      icon: Palette,
      desc: 'Parcours utilisateurs, ergonomie, User Stories et optimisation de la friction.',
      color: 'text-indigo-500'
    },
    {
      name: 'Ingénierie & Architecture',
      icon: Settings2,
      desc: 'Modèle conceptuel des données, choix de stack et architecture modulaire.',
      color: 'text-blue-500'
    },
    {
      name: 'DevOps & Sécurité',
      icon: ShieldCheck,
      desc: 'Infrastructure cloud, pipelines CI/CD et checklist de sécurité critique.',
      color: 'text-emerald-500'
    }
  ];

  return (
    <div className="flex flex-col items-center">
      {/* Hero Section */}
      <section className="w-full max-w-7xl mx-auto px-6 py-20 md:py-32 flex flex-col items-center text-center">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          className="space-y-6 max-w-4xl"
        >
          <div className="inline-flex items-center rounded-full border border-border bg-muted/50 px-3 py-1 text-xs font-medium text-muted-foreground animate-in">
            <span className="flex h-2 w-2 rounded-full bg-primary mr-2" />
            Propulsé par LangGraph & Multi-LLM
          </div>
          
          <h1 className="text-5xl md:text-7xl font-extrabold tracking-tight font-display text-foreground leading-[1.1]">
            L'excellence du développement<br />
            <span className="text-muted-foreground italic font-light">orchestrée par l'IA.</span>
          </h1>
          
          <p className="text-xl text-muted-foreground leading-relaxed max-w-2xl mx-auto">
            Transformez vos idées brutes en spécifications techniques de haut niveau. 
            Quatre départements IA spécialisés débattent pour garantir la qualité de votre futur projet.
          </p>
          
          <div className="flex flex-col sm:flex-row gap-4 justify-center pt-4">
            <Button size="lg" className="h-14 px-8 rounded-full" asChild>
              <Link href="/studio">
                <Plus className="mr-2 h-5 w-5" />
                Démarrer un projet
              </Link>
            </Button>
            <Button variant="outline" size="lg" className="h-14 px-8 rounded-full" asChild>
              <Link href="#recent-projects">
                Explorer l'historique
              </Link>
            </Button>
          </div>
        </motion.div>
      </section>

      {/* Departments Grid */}
      <section className="w-full bg-muted/30 border-y border-border py-24">
        <div className="max-w-7xl mx-auto px-6">
          <div className="flex flex-col md:flex-row md:items-end justify-between mb-12 gap-4">
            <div className="space-y-2">
              <h2 className="text-3xl font-bold font-display tracking-tight">Expertise Collaborative</h2>
              <p className="text-muted-foreground max-w-md">
                Chaque projet bénéficie de l'analyse croisée de quatre domaines d'expertise fondamentaux.
              </p>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
            {departments.map((dept, i) => (
              <motion.div
                key={i}
                initial={{ opacity: 0, y: 20 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ duration: 0.5, delay: i * 0.1 }}
              >
                <Card className="h-full border-border/50 bg-background/50 backdrop-blur-sm hover:border-primary/20 transition-colors group">
                  <CardHeader>
                    <div className={cn("p-2.5 w-fit rounded-lg bg-muted mb-4 group-hover:scale-110 transition-transform", dept.color)}>
                      <dept.icon className="h-6 w-6" />
                    </div>
                    <CardTitle className="text-lg">{dept.name}</CardTitle>
                    <CardDescription className="text-sm leading-relaxed pt-2">
                      {dept.desc}
                    </CardDescription>
                  </CardHeader>
                </Card>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* Recent Projects */}
      <section id="recent-projects" className="w-full max-w-7xl mx-auto px-6 py-24">
        <div className="flex items-center justify-between mb-10">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-primary/10 text-primary">
              <History className="h-5 w-5" />
            </div>
            <h2 className="text-2xl font-bold font-display tracking-tight">Projets Récents</h2>
          </div>
          <Button variant="ghost" size="sm" asChild>
            <Link href="/studio" className="flex items-center gap-1.5">
              Nouveau projet <ChevronRight className="h-4 w-4" />
            </Link>
          </Button>
        </div>

        {loading ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-48 rounded-xl bg-muted animate-pulse" />
            ))}
          </div>
        ) : error ? (
          <Card className="border-destructive/20 bg-destructive/5 text-destructive p-8 text-center">
            {error}
          </Card>
        ) : projects.length === 0 ? (
          <Card className="bg-muted/30 border-dashed p-16 text-center">
            <div className="max-w-xs mx-auto space-y-4">
              <div className="mx-auto w-12 h-12 rounded-full bg-muted flex items-center justify-center">
                <Plus className="h-6 w-6 text-muted-foreground" />
              </div>
              <div className="space-y-1">
                <p className="font-semibold">Aucun projet</p>
                <p className="text-sm text-muted-foreground">Commencez par créer votre premier projet dans le studio.</p>
              </div>
              <Button asChild>
                <Link href="/studio">Accéder au Studio</Link>
              </Button>
            </div>
          </Card>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {projects.map((project, idx) => (
              <motion.div
                key={project.id}
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ duration: 0.3, delay: idx * 0.05 }}
              >
                <Link href={`/projects/${project.id}`} className="group block h-full">
                  <Card className="h-full border-border/50 hover:border-primary/30 hover:shadow-lg hover:shadow-primary/5 transition-all relative overflow-hidden">
                    <CardHeader className="pb-3">
                      <div className="flex items-center justify-between gap-4 mb-2">
                        <span className={cn(
                          "text-[10px] uppercase font-bold tracking-widest px-2 py-0.5 rounded-full",
                          project.status === 'completed' ? "bg-emerald-500/10 text-emerald-500" :
                          project.status === 'running' ? "bg-primary/10 text-primary animate-pulse" :
                          project.status === 'failed' ? "bg-destructive/10 text-destructive" :
                          "bg-muted text-muted-foreground"
                        )}>
                          {project.status === 'completed' ? 'Terminé' : 
                           project.status === 'running' ? 'En cours' : 
                           project.status === 'failed' ? 'Échoué' : 'En attente'}
                        </span>
                        <span className="text-[10px] text-muted-foreground font-medium">
                          {new Date(project.created_at).toLocaleDateString('fr-FR')}
                        </span>
                      </div>
                      <CardTitle className="text-lg line-clamp-1 group-hover:text-primary transition-colors">
                        {project.title}
                      </CardTitle>
                    </CardHeader>
                    <CardContent className="pb-16">
                      <CardDescription className="line-clamp-3 text-xs leading-relaxed">
                        {project.input_text}
                      </CardDescription>
                    </CardContent>
                    <div className="absolute bottom-0 left-0 right-0 p-4 bg-gradient-to-t from-background to-transparent flex justify-between items-center">
                      <div className="text-[10px] font-semibold text-primary inline-flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                        Voir les détails <ExternalLink className="h-3 w-3" />
                      </div>
                      <button
                        onClick={(e) => handleDelete(project.id, e)}
                        className="p-2 rounded-md hover:bg-destructive/10 hover:text-destructive text-muted-foreground transition-all"
                        title="Supprimer le projet"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  </Card>
                </Link>
              </motion.div>
            ))}
          </div>
        )}
      </section>

      {/* Footer */}
      <footer className="w-full border-t border-border mt-auto">
        <div className="max-w-7xl mx-auto px-6 py-12 flex flex-col md:flex-row justify-between items-center gap-8">
          <div className="flex flex-col items-center md:items-start gap-4">
            <span className="text-lg font-bold font-display">AIA STUDIO</span>
            <p className="text-sm text-muted-foreground text-center md:text-left">
              L'agence d'IA automatisée pour vos projets web & mobile.
            </p>
          </div>
          <div className="flex gap-10 text-sm font-medium">
            <Link href="/studio" className="hover:text-primary transition-colors">Studio</Link>
            <Link href="/admin" className="hover:text-primary transition-colors">Administration</Link>
            <a href="#" className="hover:text-primary transition-colors">Documentation</a>
          </div>
          <p className="text-xs text-muted-foreground">
            © 2026 AIA Studio. Tous droits réservés.
          </p>
        </div>
      </footer>
    </div>
  );
}
