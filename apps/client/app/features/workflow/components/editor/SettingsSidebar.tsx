import React, { useEffect, useState, useMemo } from 'react';
import { useWorkflowStore } from '../../store/useWorkflowStore';
import { workflowApi } from '../../api/workflowApi';
import { DeploymentResponse } from '../../types/Deployment';
import { X, Settings, Key, Copy } from 'lucide-react';
import { toast } from 'sonner';
import { AppAuthSecretControl } from '@/app/features/app/components/AppAuthSecretControl';

const CREDENTIAL_REFERENCE_FIELDS: Record<
  string,
  { service: string; name: string }
> = {
  slackPostNode: {
    service: 'Slack',
    name: 'Slack Credential',
  },
  githubNode: {
    service: 'GitHub',
    name: 'GitHub Credential',
  },
};

export function SettingsSidebar() {
  const {
    isSettingsOpen,
    toggleSettings,
    activeWorkflowId,
    nodes,
    lastDeployedAt,
  } = useWorkflowStore();

  const [activeTab, setActiveTab] = useState<'deploy' | 'keys'>('deploy');
  const [deployments, setDeployments] = useState<DeploymentResponse[]>([]);
  const [loading, setLoading] = useState(false);

  // 배포 이력 가져오기
  const fetchDeployments = async () => {
    if (!activeWorkflowId) return;
    try {
      setLoading(true);
      const data = await workflowApi.getDeployments(activeWorkflowId);
      // 버전 내림차순 정렬
      const sorted = data.sort((a, b) => b.version - a.version);
      setDeployments(sorted);
    } catch (error) {
      console.error('Failed to fetch deployments:', error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isSettingsOpen && activeWorkflowId) {
      fetchDeployments();
    }
  }, [isSettingsOpen, activeWorkflowId, lastDeployedAt]);

  // 최신 배포 URL 필터링
  const latestDeployments = useMemo(() => {
    const latestTypes: Record<string, DeploymentResponse> = {};
    deployments.forEach((deploy) => {
      // 성공한 배포만, 그리고 이미 찾은 타입보다 버전이 높으면 갱신 (정렬되어 있으므로 첫번째가 최신)
      if (deploy.is_active && !latestTypes[deploy.type]) {
        latestTypes[deploy.type] = deploy;
      }
    });
    return Object.values(latestTypes);
  }, [deployments]);

  // 외부 연동 credential reference 집계. 원문 secret은 client state에 노출하지 않는다.
  const credentials = useMemo(() => {
    const creds: {
      id: string;
      service: string;
      name: string;
    }[] = [];

    nodes.forEach((node) => {
      const config = CREDENTIAL_REFERENCE_FIELDS[node.type || ''];
      if (config) {
        const credentialId = (node.data as { credential_id?: unknown })
          .credential_id;
        if (typeof credentialId === 'string' && credentialId) {
          creds.push({
            id: node.id,
            service: config.service,
            name: config.name,
          });
        }
      }
    });

    return creds;
  }, [nodes]);

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    toast.success('복사되었습니다.');
  };

  if (!isSettingsOpen) return null;

  return (
    <div className="absolute top-18 right-2 bottom-2 w-[400px] bg-white border-l border-gray-200 shadow-xl z-50 flex flex-col rounded-xl animate-in slide-in-from-right duration-200">
      {/* 헤더 */}
      <div className="p-4 border-b border-gray-100 flex items-center justify-between bg-white">
        <div className="flex items-center gap-2 text-gray-800">
          <Settings className="w-5 h-5" />
          <h2 className="font-semibold">설정</h2>
        </div>
        <button
          onClick={toggleSettings}
          className="p-1 hover:bg-gray-100 rounded text-gray-500"
        >
          <X className="w-5 h-5" />
        </button>
      </div>

      {/* 탭 */}
      <div className="flex border-b border-gray-200">
        <button
          className={`flex-1 py-3 text-sm font-medium transition-colors ${
            activeTab === 'deploy'
              ? 'text-blue-600 border-b-2 border-blue-600 bg-blue-50/30'
              : 'text-gray-500 hover:text-gray-700 hover:bg-gray-50'
          }`}
          onClick={() => setActiveTab('deploy')}
        >
          배포 URL
        </button>
        <button
          className={`flex-1 py-3 text-sm font-medium transition-colors ${
            activeTab === 'keys'
              ? 'text-blue-600 border-b-2 border-blue-600 bg-blue-50/30'
              : 'text-gray-500 hover:text-gray-700 hover:bg-gray-50'
          }`}
          onClick={() => setActiveTab('keys')}
        >
          외부 연동
        </button>
      </div>

      {/* 콘텐츠 */}
      <div className="flex-1 overflow-y-auto p-4">
        {activeTab === 'deploy' && (
          <div className="space-y-4">
            <p className="text-xs text-gray-500 mb-4">
              최근 성공적으로 배포된 각 타입별 URL입니다.
            </p>
            {loading ? (
              <div className="flex justify-center p-8">
                <div className="w-6 h-6 border-2 border-gray-200 border-t-blue-500 rounded-full animate-spin" />
              </div>
            ) : latestDeployments.length === 0 ? (
              <div className="text-center py-10 text-gray-400 text-sm border border-dashed rounded-lg">
                배포 기록이 없습니다.
              </div>
            ) : (
              latestDeployments.map((deploy) => {
                const origin = window.location.origin;

                // REST API
                if (deploy.type === 'api') {
                  const url = `${origin}/api/v1/run/${deploy.url_slug}`;
                  const curlCommand = `curl -X POST ${url} \\
  -H "Authorization: Bearer <APP_SECRET>" \\
  -H "Content-Type: application/json" \\
  -d '{"inputs": {}}'`;

                  return (
                    <div
                      key={deploy.id}
                      className="p-4 bg-gray-50 rounded-lg border border-gray-200 flex flex-col gap-4"
                    >
                      <div className="flex items-center justify-between">
                        <span className="px-2 py-0.5 rounded text-xs font-medium bg-purple-100 text-purple-700">
                          REST API
                        </span>
                        <span className="text-xs text-gray-500">
                          v{deploy.version}
                        </span>
                      </div>

                      {/* API Endpoint */}
                      <div>
                        <div className="text-xs font-semibold text-gray-700 mb-1">
                          API Endpoint URL
                        </div>
                        <div className="flex items-center gap-2 bg-white border border-gray-300 rounded px-2 py-1.5">
                          <div className="flex-1 text-xs text-gray-600 truncate font-mono select-all">
                            {url}
                          </div>
                          <button
                            onClick={() => copyToClipboard(url)}
                            className="p-1 hover:bg-gray-100 rounded text-gray-400 hover:text-gray-600"
                          >
                            <Copy className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </div>

                      <AppAuthSecretControl appId={deploy.app_id} />

                      {/* Test Command */}
                      <div>
                        <div className="text-xs font-semibold text-gray-700 mb-1">
                          Test Command (cURL)
                        </div>
                        <div className="relative group">
                          <pre className="text-[10px] grid overflow-x-auto p-3 bg-gray-800 text-gray-100 rounded-lg font-mono whitespace-pre-wrap break-all">
                            {curlCommand}
                          </pre>
                          <button
                            onClick={() => copyToClipboard(curlCommand)}
                            className="absolute top-2 right-2 p-1.5 bg-gray-700 text-gray-300 rounded hover:bg-gray-600 opacity-0 group-hover:opacity-100 transition-opacity"
                          >
                            <Copy className="w-3 h-3" />
                          </button>
                        </div>
                      </div>
                    </div>
                  );
                }

                // Web App
                if (deploy.type === 'webapp') {
                  const url = `${origin}/shared/${deploy.url_slug}`;
                  return (
                    <div
                      key={deploy.id}
                      className="p-4 bg-gray-50 rounded-lg border border-gray-200 flex flex-col gap-3"
                    >
                      <div className="flex items-center justify-between">
                        <span className="px-2 py-0.5 rounded text-xs font-medium bg-green-100 text-green-700">
                          WEB APP
                        </span>
                        <span className="text-xs text-gray-500">
                          v{deploy.version}
                        </span>
                      </div>

                      <div>
                        <div className="text-xs font-semibold text-gray-700 mb-1">
                          🌐 웹 앱 공유 링크
                        </div>
                        <div className="flex items-center gap-2 bg-white border border-gray-300 rounded px-2 py-1.5">
                          <div
                            className="flex-1 text-xs text-blue-600 truncate font-mono select-all underline cursor-pointer"
                            onClick={() => window.open(url, '_blank')}
                          >
                            {url}
                          </div>
                          <button
                            onClick={() => copyToClipboard(url)}
                            className="p-1 hover:bg-gray-100 rounded text-gray-400 hover:text-gray-600"
                          >
                            <Copy className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </div>
                    </div>
                  );
                }

                // Public Chatbot / Widget
                if (deploy.type === 'widget' || deploy.type === 'chatbot') {
                  if (!deploy.url_slug) {
                    return null;
                  }
                  const publicUrl = `${origin}/embed/chat/${deploy.url_slug}`;
                  const embedding = deploy.browser_access_policy?.embedding;
                  const embedCode = `<iframe
  src="${publicUrl}"
  width="100%"
  height="600"
  frameborder="0"
></iframe>`;
                  return (
                    <div
                      key={deploy.id}
                      className="p-4 bg-gray-50 rounded-lg border border-gray-200 flex flex-col gap-3"
                    >
                      <div className="flex items-center justify-between">
                        <span className="px-2 py-0.5 rounded text-xs font-medium bg-gray-200 text-gray-700">
                          {deploy.type === 'widget'
                            ? 'WIDGET'
                            : 'PUBLIC CHATBOT'}
                        </span>
                        <span className="text-xs text-gray-500">
                          v{deploy.version}
                        </span>
                      </div>

                      <div>
                        <div className="mb-1 text-xs font-semibold text-gray-700">
                          직접 링크
                        </div>
                        <div className="flex items-center gap-2 rounded border border-gray-300 bg-white px-2 py-1.5">
                          <div className="min-w-0 flex-1 truncate font-mono text-xs text-blue-600">
                            {publicUrl}
                          </div>
                          <button
                            type="button"
                            title="직접 링크 복사"
                            onClick={() => copyToClipboard(publicUrl)}
                            className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
                          >
                            <Copy className="h-3.5 w-3.5" />
                          </button>
                        </div>
                      </div>

                      <div className="text-xs text-gray-600">
                        {embedding?.enabled
                          ? `허용 origin ${embedding.parent_origins.length}개 · 집행 중`
                          : 'iframe 표시 차단'}
                      </div>

                      {embedding?.enabled && (
                        <div>
                          <div className="mb-1 text-xs font-semibold text-gray-700">
                            웹사이트 임베딩 코드
                          </div>
                          <div className="group relative">
                            <pre className="overflow-x-auto whitespace-pre-wrap break-all rounded-lg bg-gray-800 p-3 font-mono text-[10px] text-gray-100">
                              {embedCode}
                            </pre>
                            <button
                              type="button"
                              title="임베딩 코드 복사"
                              onClick={() => copyToClipboard(embedCode)}
                              className="absolute right-2 top-2 rounded bg-gray-700 p-1.5 text-gray-300 opacity-0 transition-opacity hover:bg-gray-600 group-hover:opacity-100"
                            >
                              <Copy className="h-3 w-3" />
                            </button>
                          </div>
                          <div className="mt-2 space-y-1 font-mono text-[10px] text-gray-500">
                            {embedding.parent_origins.map((parentOrigin) => (
                              <div className="break-all" key={parentOrigin}>
                                {parentOrigin}
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  );
                }

                // Fallback for others
                return (
                  <div
                    key={deploy.id}
                    className="p-3 bg-gray-50 rounded-lg border border-gray-200"
                  >
                    <div className="text-xs">Module ID: {deploy.id}</div>
                  </div>
                );
              })
            )}
          </div>
        )}

        {activeTab === 'keys' && (
          <div className="space-y-4">
            <p className="text-xs text-gray-500 mb-4">
              현재 워크플로우 노드에 연결된 외부 credential입니다.
            </p>
            {credentials.length === 0 ? (
              <div className="text-center py-10 text-gray-400 text-sm border border-dashed rounded-lg">
                연결된 external credential이 없습니다.
              </div>
            ) : (
              credentials.map((cred, idx) => (
                <div
                  key={`${cred.id}-${idx}`}
                  className="p-3 bg-white rounded-lg border border-gray-200 shadow-sm"
                >
                  <div className="flex items-center gap-2 mb-2">
                    <div className="w-8 h-8 rounded-lg bg-gray-100 flex items-center justify-center text-gray-600">
                      <Key className="w-4 h-4" />
                    </div>
                    <div>
                      <div className="font-medium text-sm text-gray-900">
                        {cred.service}
                      </div>
                      <div className="text-xs text-gray-500">{cred.name}</div>
                    </div>
                  </div>

                  <div className="rounded border border-gray-200 bg-gray-50 px-3 py-2 text-xs text-gray-600">
                    Credential 연결됨
                  </div>
                </div>
              ))
            )}
          </div>
        )}
      </div>
    </div>
  );
}
