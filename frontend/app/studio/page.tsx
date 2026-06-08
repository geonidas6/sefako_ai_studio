'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { api } from '../../lib/api';

export default function StudioPage() {
  const router = useRouter();
  const [title, setTitle] = useState('');
  const [inputText, setInputText] = useState('');
  const [assignments, setAssignments] = useState<Record<string, string>>({});
  const [loadingAssignments, setLoadingAssignments] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  // Examples list
  const examples = [
    {
      title: 'Plateforme E-learning IA',
      text: 'Créer une plateforme e-learning pour les développeurs web, avec des quiz générés par IA en temps réel, un tableau de bord de progression gamifié, et un chatbot tuteur disponible 24/7. Backend Python/FastAPI, frontend Next.js, base de données PostgreSQL.'
    },
    {
      title: 'Gestionnaire de Stock Intelligent',
      text: 'Développer une application mobile pour les gérants de petits restaurants. Elle doit permettre de scanner les factures pour mettre à jour les stocks automatiquement, prédire les ruptures de stock grâce aux ventes passées, et suggérer des commandes auprès des fournisseurs locaux.'
    },
    {
      title: 'Réseau Social Local (Entraide)',
      text: 'Créer une application web progressive (PWA) d\'entraide de quartier. Les voisins peuvent poster des besoins d\'aide (bricolage, garde d\'animaux, prêt d\'outils) géolocalisés sur une carte, avec un système de réputation basé sur des badges et un chat en temps réel.'
    }
  ];

  useEffect(() => {
    async function loadAssignments() {
      try {
        // Assignments are public enough to display, or require admin. Let's see: the GET /admin/llm-config/assignments in the backend actually depends on get_current_admin.
        // Wait, if it depends on get_current_admin, it will throw 401 if we are not logged in.
        // Let's check if the client is logged in before requesting. If they are not logged in, we can either skip or catch the error silently and show defaults.
        if (api.auth.isLoggedIn()) {
          const data = await api.admin.getAssignments();
          setAssignments(data);
        } else {
          // Default mock assignments
          setAssignments({
            strategy: 'mock',
            ux: 'mock',
            engineering: 'mock',
            devops: 'mock',
            orchestrator: 'mock'
          });
        }
      } catch (err) {
        console.error('Failed to load assignments:', err);
        // Fallback defaults
        setAssignments({
          strategy: 'mock',
          ux: 'mock',
          engineering: 'mock',
          devops: 'mock',
          orchestrator: 'mock'
        });
      } finally {
        setLoadingAssignments(false);
      }
    }
    loadAssignments();
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim() || !inputText.trim()) {
      setError('Veuillez remplir le titre et la description.');
      return;
    }

    setError('');
    setSubmitting(true);

    try {
      const proj = await api.projects.create(title, inputText);
      router.push(`/projects/${proj.id}`);
    } catch (err: any) {
      setError(err.message || 'Erreur lors de la création du projet.');
      setSubmitting(false);
    }
  };

  const selectExample = (ex: typeof examples[0]) => {
    setTitle(ex.title);
    setInputText(ex.text);
  };

  return (
    <div className="min-h-screen flex flex-col bg-[#05070f] relative overflow-hidden">
      {/* Background radial glow */}
      <div className="absolute top-[-20%] left-[-10%] w-[60%] h-[60%] rounded-full bg-violet-900/5 blur-[150px] pointer-events-none" />
      <div className="absolute bottom-[-20%] right-[-10%] w-[60%] h-[60%] rounded-full bg-cyan-900/5 blur-[150px] pointer-events-none" />

      {/* Header */}
      <header className="w-full border-b border-white/5 bg-[#090b14]/50 backdrop-blur-md sticky top-0 z-20">
        <div className="max-w-7xl mx-auto px-6 py-4 flex justify-between items-center">
          <div className="flex items-center gap-3">
            <Link href="/" className="text-xl font-bold bg-gradient-to-r from-violet-400 via-fuchsia-400 to-cyan-400 bg-clip-text text-transparent font-display tracking-wider">
              AIA STUDIO
            </Link>
            <span className="text-xs px-2.5 py-0.5 rounded-full border border-violet-500/30 bg-violet-950/20 text-violet-300 font-medium font-sans">
              Nouveau projet
            </span>
          </div>
          <Link href="/" className="text-xs text-muted-foreground hover:text-white transition-colors">
            ← Quitter le studio
          </Link>
        </div>
      </header>

      {/* Main layout */}
      <main className="flex-1 max-w-7xl mx-auto px-6 py-10 w-full z-10 grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Form Column */}
        <div className="lg:col-span-2 space-y-6">
          <div className="glass-panel p-6 rounded-2xl border border-white/5">
            <h2 className="text-xl font-bold text-white mb-2 font-display">Spécifier votre Projet</h2>
            <p className="text-muted-foreground text-xs mb-6">Fournissez un titre clair et une description détaillée des besoins. Plus vous êtes précis, plus les livrables des agents seront qualitatifs.</p>

            {error && (
              <div className="p-3 mb-4 rounded-lg bg-red-950/40 border border-red-500/20 text-red-400 text-xs font-medium">
                ⚠️ {error}
              </div>
            )}

            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1.5" htmlFor="title">
                  Titre du Projet
                </label>
                <input
                  id="title"
                  type="text"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  required
                  disabled={submitting}
                  className="w-full px-4 py-3 rounded-lg bg-white/5 border border-white/10 text-white text-sm focus:outline-none focus:border-violet-500 focus:ring-1 focus:ring-violet-500/30 transition-all placeholder:text-muted-foreground/30"
                  placeholder="Ex: SaaS de facturation automatisée pour freelances"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1.5" htmlFor="desc">
                  Description des Besoins
                </label>
                <textarea
                  id="desc"
                  value={inputText}
                  onChange={(e) => setInputText(e.target.value)}
                  required
                  disabled={submitting}
                  rows={8}
                  className="w-full px-4 py-3 rounded-lg bg-white/5 border border-white/10 text-white text-sm focus:outline-none focus:border-violet-500 focus:ring-1 focus:ring-violet-500/30 transition-all placeholder:text-muted-foreground/30 font-sans resize-y"
                  placeholder="Décrivez l'application : que doit-elle faire ? Qui sont les utilisateurs ? Quelle est la stack préférée ? Quelles sont les contraintes de sécurité importantes ?"
                />
              </div>

              <button
                type="submit"
                disabled={submitting}
                className="w-full py-4 font-bold bg-gradient-to-r from-violet-600 via-fuchsia-600 to-cyan-600 hover:from-violet-500 hover:via-fuchsia-500 hover:to-cyan-500 text-white rounded-xl shadow-lg shadow-violet-950/30 hover:shadow-violet-950/50 hover:scale-[1.01] transition-all disabled:opacity-50 disabled:pointer-events-none text-center block"
              >
                {submitting ? 'Lancement du workflow multi-agents...' : '🚀 Lancer le Débat Multi-Agents'}
              </button>
            </form>
          </div>

          {/* Examples section */}
          <div>
            <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider mb-3">Exemples de projets inspirants</h3>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {examples.map((ex, idx) => (
                <button
                  key={idx}
                  onClick={() => selectExample(ex)}
                  disabled={submitting}
                  className="glass-panel glass-panel-hover p-4 rounded-xl border border-white/5 text-left transition-all"
                >
                  <h4 className="text-xs font-bold text-white mb-1">{ex.title}</h4>
                  <p className="text-[10px] text-muted-foreground line-clamp-3 leading-relaxed">{ex.text}</p>
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Info Column (Settings Summary) */}
        <div className="space-y-6">
          {/* Agent Configuration Dashboard */}
          <div className="glass-panel p-6 rounded-2xl border border-white/5 bg-[#090b14]/50">
            <h3 className="text-sm font-bold text-white mb-1.5 font-display">Configuration Active de l'Agence</h3>
            <p className="text-[11px] text-muted-foreground mb-4">Voici les modèles affectés aux départements pour cette analyse.</p>

            {loadingAssignments ? (
              <div className="text-xs text-muted-foreground">Chargement des assignations...</div>
            ) : (
              <div className="space-y-3">
                {[
                  { key: 'strategy', label: '📈 Stratégie' },
                  { key: 'ux', label: '🎨 Conception UX' },
                  { key: 'engineering', label: '⚙️ Ingénierie' },
                  { key: 'devops', label: '🛡️ DevOps' },
                  { key: 'orchestrator', label: '🧠 Orchestrateur' },
                ].map((item) => (
                  <div key={item.key} className="flex justify-between items-center py-2 border-b border-white/5 text-xs">
                    <span className="font-medium text-muted-foreground">{item.label}</span>
                    <span className="font-mono bg-white/5 border border-white/10 px-2.5 py-0.5 rounded text-[10px] text-violet-300 font-semibold uppercase">
                      {assignments[item.key] || 'mock'}
                    </span>
                  </div>
                ))}
              </div>
            )}

            <div className="mt-4 p-3 bg-white/5 rounded-lg border border-white/5 text-[10px] text-muted-foreground leading-relaxed">
              💡 Vous souhaitez utiliser Grok, Gemini Pro ou Claude 3.5 ? Allez dans le{' '}
              <Link href="/admin" className="text-primary hover:underline font-semibold">
                Panneau Admin
              </Link>{' '}
              pour renseigner vos clés d'API et configurer les modèles.
            </div>
          </div>

          {/* How it works card */}
          <div className="glass-panel p-6 rounded-2xl border border-white/5 bg-[#090b14]/50">
            <h3 className="text-sm font-bold text-white mb-3 font-display">Déroulement de l'Analyse</h3>
            <div className="space-y-4 text-xs text-muted-foreground leading-relaxed">
              <div className="flex gap-3">
                <span className="w-5 h-5 rounded-full bg-violet-900/30 text-violet-300 border border-violet-500/20 flex items-center justify-center shrink-0 font-bold text-[10px]">1</span>
                <div>
                  <strong className="text-white block">Round 1 : Drafts Initiaux</strong>
                  Les 4 agents rédigent chacun leur proposition pour votre projet en parallèle.
                </div>
              </div>
              <div className="flex gap-3">
                <span className="w-5 h-5 rounded-full bg-violet-900/30 text-violet-300 border border-violet-500/20 flex items-center justify-center shrink-0 font-bold text-[10px]">2</span>
                <div>
                  <strong className="text-white block">Round 2 : Débat Contradictoire</strong>
                  Chaque agent examine les analyses des 3 autres et rédige une critique constructive croisée.
                </div>
              </div>
              <div className="flex gap-3">
                <span className="w-5 h-5 rounded-full bg-violet-900/30 text-violet-300 border border-violet-500/20 flex items-center justify-center shrink-0 font-bold text-[10px]">3</span>
                <div>
                  <strong className="text-white block">Round 3 : Synthèse Finale</strong>
                  L'Orchestrateur fusionne les travaux et résout les conflits pour générer la documentation finale.
                </div>
              </div>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
