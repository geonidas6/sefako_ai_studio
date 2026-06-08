import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'AIA Studio — Agence IA Multi-Agents',
  description: 'Générez des applications de bout en bout grâce à un débat collaboratif multi-agents.',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="fr">
      <head>
        <meta name="viewport" content="width=device-width, initial-scale=1.0" />
      </head>
      <body>
        {children}
      </body>
    </html>
  );
}
