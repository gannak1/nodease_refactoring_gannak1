'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Search, Plus } from 'lucide-react';

import CreateAppModal from '@/app/features/app/components/create-app-modal';
import EditAppModal from '@/app/features/app/components/edit-app-modal';
import AppCard from '@/app/features/app/components/AppCard';
import { appApi, type App } from '@/app/features/app/api/appApi';

export default function DashboardPage() {
  const router = useRouter();
  const [searchQuery, setSearchQuery] = useState('');
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [editingApp, setEditingApp] = useState<App | null>(null);
  const [apps, setApps] = useState<App[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    loadApps();

    // 사이드바에서 앱 생성 모달 이벤트 수신
    const handleOpenModal = () => {
      setIsCreateModalOpen(true);
    };

    window.addEventListener('openCreateAppModal', handleOpenModal);
    return () =>
      window.removeEventListener('openCreateAppModal', handleOpenModal);
  }, []);

  const loadApps = async () => {
    try {
      setIsLoading(true);
      setError('');
      const data = await appApi.listApps();
      setApps(data);
    } catch (err) {
      setError('앱 목록을 불러오는데 실패했습니다.');
      console.error(err);
    } finally {
      setIsLoading(false);
    }
  };

  const handleAppClick = (app: App) => {
    // workflow_id가 있으면 그것으로, 없으면 app_id로 이동
    const targetId = app.workflow_id || app.id;
    router.push(`/modules/${targetId}`);
  };

  const handleCreateApp = () => {
    setIsCreateModalOpen(true);
  };

  const handleEditApp = (e: React.MouseEvent, app: App) => {
    e.stopPropagation();
    setEditingApp(app);
  };

  const handleToggleMarketplace = async (app: App) => {
    try {
      await appApi.updateApp(app.id, {
        is_market: !app.is_market,
      });
      loadApps();
    } catch (err) {
      console.error('Failed to toggle marketplace status:', err);
      // 에러 처리 로직 추가 가능 (예: 토스트 메시지)
    }
  };

  const handleToggleDeployment = async (app: App) => {
    if (!app.active_deployment_id) {
      console.error('No active deployment found');
      return;
    }

    try {
      await appApi.toggleDeployment(app.active_deployment_id);
      loadApps(); // 앱 목록 새로고침하여 최신 배포 상태 반영
    } catch (err) {
      console.error('Failed to toggle deployment:', err);
      alert('배포 상태 변경에 실패했습니다.');
    }
  };

  const filteredApps = apps.filter((app) =>
    app.name.toLowerCase().includes(searchQuery.toLowerCase()),
  );

  return (
    <div className="min-h-full bg-slate-50 px-8 py-8">
      {/* 페이지 제목 */}
      <div className="mb-6 flex items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-black text-slate-950">내 모듈</h1>
          <p className="mt-1 text-sm font-semibold text-slate-500">
            실제 워크플로우 모듈을 만들고 관리합니다.
          </p>
        </div>

        {/* 검색 및 생성 행 */}
        <div className="flex items-center justify-end gap-3">
          {/* 검색바 */}
          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              type="text"
              placeholder="내 모듈 검색"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="h-10 w-64 rounded-md border border-slate-200 bg-white py-2 pl-9 pr-4 text-sm font-semibold text-slate-900 placeholder:text-slate-400 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-100"
            />
          </div>

          {/* 생성 버튼 */}
          <button
            onClick={handleCreateApp}
            className="flex h-10 items-center gap-2 rounded-md bg-slate-950 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-slate-800"
          >
            <Plus className="w-4 h-4" />새 모듈
          </button>
        </div>
      </div>

      {/* 에러 메시지 */}
      {error && (
        <div className="mb-6 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm font-semibold text-red-700">
          {error}
        </div>
      )}

      {/* 로딩 상태 */}
      {isLoading && (
        <div className="text-center py-12">
          <p className="text-sm font-semibold text-slate-500">로딩 중...</p>
        </div>
      )}

      {/* 모듈 카드 그리드 */}
      {/* 앱 그리드 */}
      {!isLoading && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {/* 기존 앱 카드 */}
          {filteredApps.map((app) => (
            <AppCard
              key={app.id}
              app={app}
              onClick={handleAppClick}
              onEdit={handleEditApp}
              onToggleMarketplace={handleToggleMarketplace}
              onToggleDeployment={handleToggleDeployment}
              onRefresh={loadApps}
            />
          ))}
        </div>
      )}

      {/* 검색 결과 없음 상태 */}
      {!isLoading && filteredApps.length === 0 && searchQuery && (
        <div className="mt-12 text-center">
          <p className="text-sm font-semibold text-slate-500">
            &quot;{searchQuery}&quot;에 대한 검색 결과가 없습니다.
          </p>
        </div>
      )}

      {/* 앱 생성 모달 */}
      {isCreateModalOpen && (
        <CreateAppModal
          onClose={() => setIsCreateModalOpen(false)}
          onSuccess={() => {
            setIsCreateModalOpen(false);
            loadApps(); // 목록 새로고침
          }}
        />
      )}

      {/* 앱 수정 모달 */}
      {editingApp && (
        <EditAppModal
          app={editingApp}
          onClose={() => setEditingApp(null)}
          onSuccess={() => {
            setEditingApp(null);
            loadApps(); // 목록 새로고침
          }}
        />
      )}
    </div>
  );
}
