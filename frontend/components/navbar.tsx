'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { cn } from '@/lib/utils';
import { FolderKanban, PenTool, Settings, Home } from 'lucide-react';

export function Navbar() {
  const pathname = usePathname();

  const navItems = [
    { label: 'Accueil', href: '/', icon: Home },
    { label: 'Studio', href: '/studio', icon: PenTool },
    { label: 'Projets', href: '/projects', icon: FolderKanban },
    { label: 'Administration', href: '/admin', icon: Settings },
  ];

  return (
    <header className="sticky top-0 z-50 w-full border-b border-border/40 bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="container flex h-16 max-w-7xl mx-auto items-center justify-between px-6">
        <div className="flex items-center gap-2">
          <Link href="/" className="flex items-center space-x-2">
            <span className="text-xl font-bold font-display bg-gradient-to-r from-foreground to-foreground/70 bg-clip-text text-transparent">
              AIA STUDIO
            </span>
            <span className="hidden sm:inline-block px-2 py-0.5 rounded-full border border-border bg-muted/50 text-[10px] font-medium text-muted-foreground uppercase tracking-tighter">
              v1.2
            </span>
          </Link>
        </div>

        <nav className="flex items-center gap-6">
          {navItems.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex items-center gap-2 text-sm font-medium transition-colors hover:text-primary",
                pathname === item.href || (item.href !== '/' && pathname.startsWith(item.href))
                  ? "text-primary"
                  : "text-muted-foreground"
              )}
            >
              <item.icon className="h-4 w-4" />
              <span className="hidden md:inline-block">{item.label}</span>
            </Link>
          ))}
          <Link
            href="/studio"
            className="hidden sm:inline-flex h-9 items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground shadow transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50"
          >
            Lancer un projet
          </Link>
        </nav>
      </div>
    </header>
  );
}
