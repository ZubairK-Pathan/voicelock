'use client';

import Link from 'next/link';

export default function NotFound() {
  return (
    <div className="flex flex-col items-center justify-center min-h-screen bg-background">
      <h1 className="text-6xl font-bold text-text-primary">404</h1>
      <p className="text-xl text-text-secondary mt-4">Page not found</p>
      <Link
        href="/"
        className="mt-8 btn btn-primary"
      >
        Go back home
      </Link>
    </div>
  );
}