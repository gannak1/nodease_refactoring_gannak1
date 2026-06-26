'use client';

import { ChevronRight } from 'lucide-react';
import { useParams, useRouter } from 'next/navigation';
import { useWorkflowStore } from '@/app/features/workflow/store/useWorkflowStore';
import { isMockWorkflowId } from '../../utils/mockMode';

export default function EditorHeader() {
  const router = useRouter();
  const params = useParams();
  const { projectApp } = useWorkflowStore();
  const isMockMode = isMockWorkflowId(params.id as string);

  return (
    <header className="relative z-50 flex h-12 min-h-[48px] items-center justify-between border-b border-slate-200 bg-white px-5">
      {/* 1. Left: Breadcrumb */}
      <nav className="ml-2 flex items-center gap-2 text-sm">
        <button
          onClick={() => router.push('/dashboard/mymodule')}
          className="font-semibold text-slate-500 transition-colors hover:text-slate-950"
        >
          내 모듈
        </button>
        <ChevronRight className="h-4 w-4 text-slate-400" />
        <span className="font-black text-slate-950">
          {projectApp?.name || '이름 없는 모듈'}
        </span>
        {isMockMode && (
          <span className="rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[11px] font-semibold text-amber-700">
            Mock 모드 · 저장 안 됨
          </span>
        )}
      </nav>
    </header>
  );
}
