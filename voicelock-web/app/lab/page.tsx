'use client';

import { PageHeader } from '@/components/ui/PageHeader';
import { Card } from '@/components/ui/Card';
import { ComingSoon } from '@/components/ui/States';

export default function LabPage() {
  return (
    <>
      <PageHeader
        title="Lab"
        description="Biometric performance and analysis"
      />

      <Card>
        <ComingSoon />
      </Card>
    </>
  );
}