'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { api } from '@/lib/api';
import { Loader2 } from 'lucide-react';

interface AuthGuardProps {
  children: React.ReactNode;
}

/**
 * AuthGuard — wraps any page that requires authentication.
 * If the user is not logged in (no valid JWT in localStorage),
 * they are immediately redirected to /admin/login.
 * While the check is running a full-screen loader is shown so the
 * protected content never flashes to an unauthenticated visitor.
 */
export function AuthGuard({ children }: AuthGuardProps) {
  const router = useRouter();
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    if (!api.auth.isLoggedIn()) {
      router.replace('/admin/login');
    } else {
      setChecking(false);
    }

    // Also react to token-expiry events dispatched by the api layer
    const handleAuthExpired = () => {
      api.auth.logout();
      router.replace('/admin/login');
    };
    window.addEventListener('aia-auth-expired', handleAuthExpired as EventListener);
    return () => window.removeEventListener('aia-auth-expired', handleAuthExpired as EventListener);
  }, [router]);

  if (checking) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  return <>{children}</>;
}
