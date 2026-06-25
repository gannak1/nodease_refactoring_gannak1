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
    <header className="h-10 min-h-[40px] bg-white flex items-center px-4 justify-between relative z-50">
      {/* 1. Left: Breadcrumb */}
      <nav className="flex items-center gap-2 text-sm ml-2">
        <button
          onClick={() => router.push('/dashboard/mymodule')}
          className="text-gray-600 hover:text-gray-900 transition-colors"
        >
          내 모듈
        </button>
        <ChevronRight className="w-4 h-4 text-gray-400" />
        <span className="font-medium text-gray-900">
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
