'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { api } from '../../../lib/api';

export default function AdminLoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    // If already logged in, redirect to admin
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
    <div className="min-h-screen flex flex-col items-center justify-center bg-[#05070f] px-6 relative overflow-hidden">
      {/* Background radial glow */}
      <div className="absolute w-[500px] h-[500px] rounded-full bg-violet-600/5 blur-[100px] top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 pointer-events-none" />

      <div className="w-full max-w-md z-10">
        {/* Logo */}
        <div className="text-center mb-8">
          <Link href="/" className="inline-block text-3xl font-bold bg-gradient-to-r from-violet-400 via-fuchsia-400 to-cyan-400 bg-clip-text text-transparent font-display tracking-wider mb-2">
            AIA STUDIO
          </Link>
          <p className="text-muted-foreground text-xs font-medium uppercase tracking-widest">Panneau d'Administration</p>
        </div>

        {/* Card */}
        <div className="glass-panel p-8 rounded-2xl border border-white/5 bg-[#090b14]/50 shadow-2xl">
          <h2 className="text-xl font-bold text-white mb-6 font-display">Connexion Administrateur</h2>

          {error && (
            <div className="p-3 mb-4 rounded-lg bg-red-950/40 border border-red-500/20 text-red-400 text-xs font-medium">
              ⚠️ {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1.5" htmlFor="username">
                Nom d'utilisateur
              </label>
              <input
                id="username"
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
                className="w-full px-4 py-3 rounded-lg bg-white/5 border border-white/10 text-white text-sm focus:outline-none focus:border-violet-500 focus:ring-1 focus:ring-violet-500/30 transition-all placeholder:text-muted-foreground/50"
                placeholder="Ex: admin"
              />
            </div>

            <div>
              <label className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1.5" htmlFor="password">
                Mot de passe
              </label>
              <input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                className="w-full px-4 py-3 rounded-lg bg-white/5 border border-white/10 text-white text-sm focus:outline-none focus:border-violet-500 focus:ring-1 focus:ring-violet-500/30 transition-all placeholder:text-muted-foreground/50"
                placeholder="••••••••"
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full py-3 mt-2 font-bold bg-gradient-to-r from-violet-600 to-cyan-600 hover:from-violet-500 hover:to-cyan-500 text-white rounded-lg shadow-lg shadow-violet-950/20 transition-all active:scale-[0.98] disabled:opacity-50 disabled:pointer-events-none"
            >
              {loading ? 'Connexion en cours...' : 'Se connecter'}
            </button>
          </form>

          <div className="mt-6 text-center">
            <Link href="/" className="text-xs text-muted-foreground hover:text-white transition-colors">
              ← Retour à l'accueil
            </Link>
          </div>
        </div>

        {/* First run info */}
        <div className="mt-6 text-center text-xs text-muted-foreground/60 max-w-sm mx-auto leading-relaxed">
          Pour la première connexion, utilisez les identifiants configurés par défaut dans l'application : <code className="text-violet-400 font-mono">admin</code> / <code className="text-violet-400 font-mono">Admin@AIA2026!</code>
        </div>
      </div>
    </div>
  );
}
