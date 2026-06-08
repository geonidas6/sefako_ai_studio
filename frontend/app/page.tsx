'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { api } from '../lib/api';

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
      icon: '📈',
      desc: 'Analyse de viabilité marché, KPIs de succès, modélisation business model, positionnement concurrentiel et MVP strategy.',
      color: 'from-pink-500/20 to-purple-500/20 border-pink-500/30'
    },
    {
      name: 'Conception & UX',
      icon: '🎨',
      desc: 'Parcours utilisateurs détaillés, points de friction, conception ergonomique, parcours clés et spécification des User Stories.',
      color: 'from-purple-500/20 to-indigo-500/20 border-purple-500/30'
    },
    {
      name: 'Ingénierie & Architecture',
      icon: '⚙️',
      desc: 'Modèle conceptuel des données (MCD), choix de la stack technologique modulaire, architecture backend/frontend et risques techniques.',
      color: 'from-blue-500/20 to-cyan-500/20 border-blue-500/30'
    },
    {
      name: 'DevOps & Sécurité',
      icon: '🛡️',
      desc: 'Infrastructures cloud modernes, pipelines CI/CD automatisés, checklist de sécurité critique et plan de monitoring applicatif.',
      color: 'from-cyan-500/20 to-emerald-500/20 border-cyan-500/30'
    }
  ];

  return (
    <div className="min-h-screen flex flex-col bg-[#05070f] relative overflow-hidden">
      {/* Background gradients */}
      <div className="absolute top-[-10%] left-[-10%] w-[50%] h-[50%] rounded-full bg-purple-900/10 blur-[120px] pointer-events-none" />
      <div className="absolute bottom-[-10%] right-[-10%] w-[50%] h-[50%] rounded-full bg-cyan-900/10 blur-[120px] pointer-events-none" />

      {/* Header */}
      <header className="w-full max-w-7xl mx-auto px-6 py-6 flex justify-between items-center z-10">
        <div className="flex items-center gap-3">
          <span className="text-2xl font-bold bg-gradient-to-r from-violet-400 via-fuchsia-400 to-cyan-400 bg-clip-text text-transparent font-display tracking-wider">
            AIA STUDIO
          </span>
          <span className="text-xs px-2.5 py-0.5 rounded-full border border-violet-500/30 bg-violet-950/20 text-violet-300 font-medium font-sans">
            v1.2
          </span>
        </div>
        <div className="flex items-center gap-4">
          <Link
            href="/admin"
            className="text-sm text-muted-foreground hover:text-foreground transition-colors px-4 py-2 rounded-md hover:bg-white/5 border border-transparent hover:border-white/10"
          >
            Administration
          </Link>
          <Link
            href="/studio"
            className="text-sm font-semibold bg-gradient-to-r from-violet-600 to-cyan-600 hover:from-violet-500 hover:to-cyan-500 text-white px-5 py-2.5 rounded-lg shadow-lg shadow-violet-900/20 hover:shadow-violet-900/40 transition-all hover:scale-[1.02]"
          >
            Lancer un projet
          </Link>
        </div>
      </header>

      {/* Main content */}
      <main className="flex-1 max-w-7xl mx-auto px-6 w-full z-10 flex flex-col items-center pt-12 pb-24">
        {/* Hero Section */}
        <section className="text-center max-w-3xl mb-16">
          <h1 className="text-4xl md:text-6xl font-extrabold tracking-tight font-display mb-6 leading-tight">
            Agence IA{' '}
            <span className="bg-gradient-to-r from-violet-400 via-fuchsia-400 to-cyan-400 bg-clip-text text-transparent glow-text">
              Multi-Agents
            </span>
          </h1>
          <p className="text-lg text-muted-foreground leading-relaxed mb-8">
            Collaborez avec un collectif d'agents IA spécialisés. Soumettez votre idée, laissez les départements débattre, critiquer et converger vers des livrables de niveau expert : CDC, MCD, Architecture et Roadmap.
          </p>
          <div className="flex flex-col sm:flex-row gap-4 justify-center">
            <Link
              href="/studio"
              className="px-8 py-4 bg-gradient-to-r from-violet-600 via-fuchsia-600 to-cyan-600 hover:from-violet-500 hover:via-fuchsia-500 hover:to-cyan-500 text-white font-bold rounded-xl shadow-xl shadow-violet-950/30 hover:shadow-violet-950/50 hover:scale-[1.02] active:scale-[0.98] transition-all text-center"
            >
              🚀 Lancer un Nouveau Projet
            </Link>
            <Link
              href="#recent-projects"
              className="px-8 py-4 bg-white/5 hover:bg-white/10 border border-white/10 hover:border-white/20 text-white font-bold rounded-xl transition-all text-center"
            >
              📂 Parcourir l'historique
            </Link>
          </div>
        </section>

        {/* Departments grid */}
        <section className="w-full mb-24">
          <div className="text-center mb-12">
            <h2 className="text-2xl md:text-3xl font-bold font-display mb-2">Les 4 Départements IA de l'Agence</h2>
            <p className="text-muted-foreground text-sm max-w-xl mx-auto">
              Chaque département intervient à chaque round pour raffiner, challenger et valider vos spécifications.
            </p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
            {departments.map((dept, i) => (
              <div
                key={i}
                className={`glass-panel glass-panel-hover p-6 rounded-xl border bg-gradient-to-br ${dept.color}`}
              >
                <div className="text-3xl mb-4">{dept.icon}</div>
                <h3 className="text-lg font-bold font-display mb-2 text-white">{dept.name}</h3>
                <p className="text-sm text-muted-foreground leading-relaxed">{dept.desc}</p>
              </div>
            ))}
          </div>
        </section>

        {/* Project history section */}
        <section id="recent-projects" className="w-full max-w-4xl scroll-mt-24">
          <div className="flex justify-between items-center mb-6">
            <h2 className="text-xl md:text-2xl font-bold font-display">Projets récents</h2>
            <Link href="/studio" className="text-xs text-primary hover:underline font-medium">
              + Créer un projet
            </Link>
          </div>

          {loading ? (
            <div className="glass-panel rounded-xl p-12 text-center text-muted-foreground border border-white/5">
              Chargement des projets...
            </div>
          ) : error ? (
            <div className="glass-panel rounded-xl p-12 text-center text-red-400 border border-red-500/20 bg-red-950/5">
              {error}
            </div>
          ) : projects.length === 0 ? (
            <div className="glass-panel rounded-xl p-12 text-center text-muted-foreground border border-white/5">
              <span className="block text-3xl mb-3">📂</span>
              Aucun projet pour le moment. Lisez le cahier des charges et lancez votre premier projet !
            </div>
          ) : (
            <div className="flex flex-col gap-4">
              {projects.map((project) => (
                <Link
                  key={project.id}
                  href={`/projects/${project.id}`}
                  className="glass-panel glass-panel-hover p-5 rounded-xl border border-white/5 flex items-center justify-between gap-4 group"
                >
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-3 mb-1">
                      <h3 className="text-base font-semibold text-white group-hover:text-primary transition-colors truncate">
                        {project.title}
                      </h3>
                      <span
                        className={`text-xs px-2 py-0.5 rounded-full font-medium ${
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
                    <p className="text-xs text-muted-foreground truncate">{project.input_text}</p>
                  </div>
                  <div className="flex items-center gap-4 text-xs text-muted-foreground">
                    <span>{new Date(project.created_at).toLocaleDateString('fr-FR')}</span>
                    <button
                      onClick={(e) => handleDelete(project.id, e)}
                      className="p-2 rounded-md hover:bg-red-950/30 hover:text-red-400 border border-transparent hover:border-red-500/20 transition-all"
                      title="Supprimer le projet"
                    >
                      🗑️
                    </button>
                  </div>
                </Link>
              ))}
            </div>
          )}
        </section>
      </main>

      {/* Footer */}
      <footer className="w-full max-w-7xl mx-auto px-6 py-8 border-t border-white/5 flex flex-col sm:flex-row justify-between items-center gap-4 text-xs text-muted-foreground z-10">
        <div>© 2026 AIA Studio. Tous droits réservés.</div>
        <div className="flex gap-4">
          <Link href="/studio" className="hover:text-foreground transition-colors">Studio</Link>
          <span>•</span>
          <Link href="/admin" className="hover:text-foreground transition-colors">Admin Panel</Link>
        </div>
      </footer>
    </div>
  );
}
