'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { motion } from 'framer-motion';
import { 
  Sparkles, 
  Lightbulb, 
  Info, 
  Cpu, 
  ChevronLeft,
  Rocket
} from 'lucide-react';
import { api } from '../../lib/api';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { AuthGuard } from '@/components/auth-guard';

export default function StudioPage() {
  const router = useRouter();
  const [title, setTitle] = useState('');
  const [inputText, setInputText] = useState('');
  const [assignments, setAssignments] = useState<Record<string, string>>({});
  const [loadingAssignments, setLoadingAssignments] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  const examples = [
    {
      title: 'Plateforme E-learning IA',
      text: 'Plateforme e-learning avec quiz générés par IA, tableau de bord gamifié et tuteur chatbot 24/7. Backend FastAPI, frontend Next.js.'
    },
    {
      title: 'Gestionnaire de Stock',
      text: 'Application mobile pour restaurants : scan de factures, prédiction de ruptures et suggestions de commandes fournisseurs.'
    },
    {
      title: 'Réseau Social Local',
      text: 'PWA d\'entraide de quartier avec besoins géolocalisés, système de réputation par badges et chat en temps réel.'
    }
  ];

  useEffect(() => {
    async function loadAssignments() {
      try {
        if (api.auth.isLoggedIn()) {
          const data = await api.admin.getAssignments();
          setAssignments(data);
        } else {
          setAssignments({
            strategy: 'mock',
            ux: 'mock',
            engineering: 'mock',
            devops: 'mock',
            orchestrator: 'mock'
          });
        }
      } catch (err) {
        setAssignments({
          strategy: 'mock', ux: 'mock', engineering: 'mock', devops: 'mock', orchestrator: 'mock'
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

  return (
    <AuthGuard>
    <div className="max-w-7xl mx-auto px-6 py-12 md:py-20">
      <motion.div 
        initial={{ opacity: 0, x: -20 }}
        animate={{ opacity: 1, x: 0 }}
        className="mb-10"
      >
        <Link href="/" className="inline-flex items-center text-sm text-muted-foreground hover:text-foreground transition-colors mb-4">
          <ChevronLeft className="mr-1 h-4 w-4" /> Retour à l'accueil
        </Link>
        <h1 className="text-3xl md:text-4xl font-bold font-display tracking-tight">Studio de Conception</h1>
        <p className="text-muted-foreground mt-2">Définissez votre vision, nos agents s'occupent du reste.</p>
      </motion.div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-10">
        {/* Form Section */}
        <div className="lg:col-span-2 space-y-8">
          <Card className="border-border/60 shadow-xl shadow-black/20">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Sparkles className="h-5 w-5 text-primary" />
                Détails du projet
              </CardTitle>
              <CardDescription>
                Soyez aussi précis que possible pour obtenir des résultats de haute qualité.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <form onSubmit={handleSubmit} className="space-y-6">
                <div className="space-y-2">
                  <label className="text-sm font-semibold text-foreground" htmlFor="title">Titre du Projet</label>
                  <Input 
                    id="title"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    placeholder="Ex: SaaS de facturation automatisée"
                    disabled={submitting}
                  />
                </div>

                <div className="space-y-2">
                  <label className="text-sm font-semibold text-foreground" htmlFor="desc">Description détaillée</label>
                  <textarea
                    id="desc"
                    value={inputText}
                    onChange={(e) => setInputText(e.target.value)}
                    placeholder="Que doit faire l'application ? Quels sont les utilisateurs cibles ? Quelles sont les fonctionnalités clés ?"
                    rows={10}
                    disabled={submitting}
                    className="flex w-full rounded-md border border-input bg-muted/50 px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring transition-all resize-y min-h-[200px]"
                  />
                </div>

                {error && (
                  <div className="p-4 rounded-lg bg-destructive/10 border border-destructive/20 text-destructive text-sm flex items-start gap-2">
                    <Info className="h-4 w-4 mt-0.5 shrink-0" />
                    {error}
                  </div>
                )}

                <Button 
                  type="submit" 
                  disabled={submitting} 
                  className="w-full h-12 text-base font-bold rounded-xl"
                >
                  {submitting ? (
                    <span className="flex items-center gap-2">
                      <span className="h-4 w-4 rounded-full border-2 border-primary-foreground/30 border-t-primary-foreground animate-spin" />
                      Initialisation de l'agence...
                    </span>
                  ) : (
                    <span className="flex items-center gap-2">
                      <Rocket className="h-5 w-5" />
                      Lancer le Débat Multi-Agents
                    </span>
                  )}
                </Button>
              </form>
            </CardContent>
          </Card>

          {/* Examples */}
          <div className="space-y-4">
            <div className="flex items-center gap-2 text-sm font-semibold text-muted-foreground uppercase tracking-wider">
              <Lightbulb className="h-4 w-4" /> Exemples d'inspiration
            </div>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {examples.map((ex, idx) => (
                <button
                  key={idx}
                  onClick={() => { setTitle(ex.title); setInputText(ex.text); }}
                  className="text-left p-4 rounded-xl border border-border bg-background hover:border-primary/40 hover:bg-muted/30 transition-all group"
                >
                  <h4 className="text-xs font-bold mb-1 group-hover:text-primary transition-colors">{ex.title}</h4>
                  <p className="text-[10px] text-muted-foreground line-clamp-2">{ex.text}</p>
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Info Column */}
        <div className="space-y-6">
          <Card className="bg-muted/30 border-border/40">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm flex items-center gap-2">
                <Cpu className="h-4 w-4 text-primary" />
                Configuration de l'Agence
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                {[
                  { key: 'strategy', label: 'Stratégie' },
                  { key: 'ux', label: 'Conception UX' },
                  { key: 'engineering', label: 'Ingénierie' },
                  { key: 'devops', label: 'DevOps' },
                  { key: 'orchestrator', label: 'Orchestrateur' },
                ].map((item) => (
                  <div key={item.key} className="flex justify-between items-center py-2 border-b border-border/50 last:border-0">
                    <span className="text-xs font-medium text-muted-foreground">{item.label}</span>
                    <span className="text-[10px] font-mono bg-background px-2 py-0.5 rounded border border-border text-primary font-bold uppercase">
                      {loadingAssignments ? '...' : (assignments[item.key] || 'mock')}
                    </span>
                  </div>
                ))}
              </div>
              <p className="text-[10px] text-muted-foreground leading-relaxed italic">
                La configuration des modèles peut être modifiée dans le <Link href="/admin" className="text-primary hover:underline underline-offset-2">panneau d'administration</Link>.
              </p>
            </CardContent>
          </Card>

          <Card className="bg-primary/5 border-primary/10">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm">Déroulement de l'analyse</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4 text-xs">
              {[
                { step: 1, title: 'Analyses initiales', desc: 'Chaque département produit une proposition indépendante.' },
                { step: 2, title: 'Débat contradictoire', desc: 'Les agents s\'autocritiquent pour lever les incohérences.' },
                { step: 3, title: 'Synthèse finale', desc: 'Fusion des travaux en livrables exploitables.' },
              ].map((item) => (
                <div key={item.step} className="flex gap-3">
                  <div className="h-5 w-5 rounded-full bg-primary text-primary-foreground flex items-center justify-center shrink-0 font-bold text-[10px]">
                    {item.step}
                  </div>
                  <div className="space-y-0.5">
                    <p className="font-bold">{item.title}</p>
                    <p className="text-muted-foreground leading-snug">{item.desc}</p>
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
    </AuthGuard>
  );
}
