import type { ReactNode } from 'react';

import './globals.css';

export const metadata = {
  title: 'Coverset',
  description: 'Agentic scheduling partner for first assistant directors',
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
