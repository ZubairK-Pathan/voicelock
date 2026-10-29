'use client';

import { PageHeader } from '@/components/ui/PageHeader';
import { Card } from '@/components/ui/Card';
import { ComingSoon } from '@/components/ui/States';

export default function AuditPage() {
  return (
    <>
      <PageHeader
        title="Audit"
        description="System audit logs and analytics"
      />

      <Card>
        <ComingSoon />
      </Card>
    </>
  );
}