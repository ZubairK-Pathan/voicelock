'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { PageHeader } from '@/components/ui/PageHeader';
import { Card } from '@/components/ui/Card';
import { LoadingState, ErrorState, EmptyState } from '@/components/ui/States';
import { useApiResource } from '@/lib/hooks/useApiResource';
import { api } from '@/lib/api/client';
import { useState } from 'react';

export default function SpeakersPage() {
  const router = useRouter();
  const [searchTerm, setSearchTerm] = useState('');
  const { data, loading, error, reload } = useApiResource(() =>
    api.listSpeakers()
  );

  const filteredSpeakers = data?.speakers.filter((speaker) =>
    speaker.name.toLowerCase().includes(searchTerm.toLowerCase())
  ) || [];

  return (
    <>
      <PageHeader
        title="Speakers"
        description="Manage enrolled speakers"
        action={{
          label: '+ Enroll Speaker',
          onClick: () => router.push('/speakers/enroll'),
        }}
      />

      {/* Search */}
      <div className="mb-6">
        <input
          type="text"
          placeholder="Search speakers..."
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          className="input"
        />
      </div>

      {/* Content */}
      {loading && <LoadingState />}
      {error && <ErrorState message={error.message} />}
      {!loading && !error && filteredSpeakers.length === 0 && (
        <EmptyState message="No speakers enrolled yet" />
      )}

      {!loading && !error && filteredSpeakers.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filteredSpeakers.map((speaker) => (
            <Card key={speaker.name} className="hover:shadow-md transition-shadow">
              <Link href={`/speakers/${encodeURIComponent(speaker.name)}`}>
                <h3 className="text-lg font-semibold text-text-primary hover:text-blue-500">
                  {speaker.name}
                </h3>
              </Link>
              <p className="text-text-secondary text-sm mt-2">
                Enrolled: {new Date(speaker.enrollment_date).toLocaleDateString()}
              </p>
              <p className="text-text-tertiary text-sm">
                {speaker.num_samples} sample{speaker.num_samples !== 1 ? 's' : ''}
              </p>
            </Card>
          ))}
        </div>
      )}
    </>
  );
}