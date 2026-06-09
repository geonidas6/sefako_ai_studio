'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { motion } from 'framer-motion';
import { Lock, AlertCircle, Loader2, ChevronLeft } from 'lucide-react';
import { api } from '../../../lib/api';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Input } from '@/components/ui/input';

export default function AdminLoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (api.auth.isLoggedIn()) {
      router.push('/admin');
    }
  }, [router]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await api.auth.login(username, password);
      router.push('/admin');
    } catch (err: any) {
      setError(err.message || 'Identifiants invalides');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-[calc(100vh-64px)] flex flex-col items-center justify-center p-6 bg-background relative overflow-hidden">
      <motion.div
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.3 }}
        className="w-full max-w-md z-10"
      >
        <div className="text-center mb-10">
          <Link href="/" className="inline-block text-4xl font-extrabold font-display tracking-tight mb-3">
            AIA STUDIO
          </Link>
          <p className="text-muted-foreground text-sm font-medium uppercase tracking-[0.2em] opacity-60">Admin Gateway</p>
        </div>

        <Card className="border-border/60 shadow-2xl shadow-black/40">
          <CardHeader className="text-center pb-2">
            <div className="mx-auto w-12 h-12 rounded-full bg-primary/10 flex items-center justify-center mb-4">
              <Lock className="h-6 w-6 text-primary" />
            </div>
            <CardTitle className="text-2xl font-display">Authentification</CardTitle>
            <CardDescription>Accédez à la gestion des modèles et agents.</CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSubmit} className="space-y-5">
              <div className="space-y-2">
                <label className="text-xs font-bold text-muted-foreground uppercase" htmlFor="username">Utilisateur</label>
                <Input
                  id="username"
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="admin"
                  required
                />
              </div>

              <div className="space-y-2">
                <label className="text-xs font-bold text-muted-foreground uppercase" htmlFor="password">Mot de passe</label>
                <Input
                  id="password"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  required
                />
              </div>

              {error && (
                <div className="p-3 rounded-lg bg-destructive/10 border border-destructive/20 text-destructive text-xs font-medium flex items-center gap-2">
                  <AlertCircle className="h-4 w-4" /> {error}
                </div>
              )}

              <Button type="submit" disabled={loading} className="w-full h-11 text-base font-bold">
                {loading ? <Loader2 className="h-5 w-5 animate-spin" /> : 'Se connecter'}
              </Button>
            </form>

            <div className="mt-8 flex justify-center">
              <Link href="/" className="inline-flex items-center text-xs text-muted-foreground hover:text-foreground transition-colors">
                <ChevronLeft className="mr-1 h-3.5 w-3.5" /> Retour à l'accueil
              </Link>
            </div>
          </CardContent>
        </Card>

        <div className="mt-8 text-center">
          <p className="text-[10px] text-muted-foreground/40 leading-relaxed max-w-[280px] mx-auto">
            Accès réservé au personnel autorisé. Toute tentative de connexion non autorisée est enregistrée.
          </p>
        </div>
      </motion.div>
    </div>
  );
}
