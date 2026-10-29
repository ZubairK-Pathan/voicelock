'use client';

import { PageHeader } from '@/components/ui/PageHeader';
import { Card } from '@/components/ui/Card';
import { ComingSoon } from '@/components/ui/States';

export default function AuthPage() {
  return (
    <>
      <PageHeader
        title="Authentication"
        description="Voice-based speaker verification"
      />

      <Card>
        <ComingSoon />
      </Card>
    </>
  );
}