import { useCallback, useMemo } from 'react';
import { useWorkflowStore } from '@/app/features/workflow/store/useWorkflowStore';
import { MailNodeData, EmailProvider } from '../../../../types/Nodes';
import { CollapsibleSection } from '../../ui/CollapsibleSection';
import { RoundedSelect } from '../../../ui/RoundedSelect';
import { ValidationAlert } from '../../../ui/ValidationAlert';
import { getUpstreamNodes } from '../../../../utils/getUpstreamNodes';
import {
  DraggedOutputVariable,
  getDroppedOutputReferenceName,
  getTokenLabelMap,
  upsertNamedSelector,
} from '../../../../utils/nodeVariablePorts';
import { VariableTokenEditor } from '../../ui/VariableTokenEditor';

interface MailNodePanelProps {
  nodeId: string;
  data: MailNodeData;
}

// 노드 실행 필수 요건 체크
// 1. SMTP 서버 설정(호스트, 포트, 사용자)이 완료되어야 함
// 2. 수신자 이메일이 입력되어야 함
// 3. 제목과 본문이 입력되어야 함

// Provider별 IMAP 서버 프리셋
const PROVIDER_PRESETS: Record<
  Exclude<EmailProvider, 'custom'>,
  { imap_server: string; imap_port: number; use_ssl: boolean }
> = {
  gmail: {
    imap_server: 'imap.gmail.com',
    imap_port: 993,
    use_ssl: true,
  },
  naver: {
    imap_server: 'imap.naver.com',
    imap_port: 993,
    use_ssl: true,
  },
  daum: {
    imap_server: 'imap.daum.net',
    imap_port: 993,
    use_ssl: true,
  },
  outlook: {
    imap_server: 'outlook.office365.com',
    imap_port: 993,
    use_ssl: true,
  },
};

export function MailNodePanel({ nodeId, data }: MailNodePanelProps) {
  const { updateNodeData, nodes, edges } = useWorkflowStore();
  const upstreamNodes = useMemo(
    () => getUpstreamNodes(nodeId, nodes, edges),
    [nodeId, nodes, edges],
  );

  const handleUpdateData = useCallback(
    (key: keyof MailNodeData, value: unknown) => {
      updateNodeData(nodeId, { [key]: value });
    },
    [nodeId, updateNodeData],
  );

  // Provider 변경 핸들러
  const handleProviderChange = useCallback(
    (provider: EmailProvider) => {
      handleUpdateData('provider', provider);

      // Custom이 아니면 프리셋 자동 설정
      if (provider !== 'custom') {
        const preset = PROVIDER_PRESETS[provider];
        handleUpdateData('imap_server', preset.imap_server);
        handleUpdateData('imap_port', preset.imap_port);
        handleUpdateData('use_ssl', preset.use_ssl);
      } else {
        // Custom 선택 시 예시 값 설정
        handleUpdateData('imap_server', 'imap.example.com');
        handleUpdateData('imap_port', 993);
        handleUpdateData('use_ssl', true);
      }
    },
    [handleUpdateData],
  );

  const emailMissing = useMemo(() => {
    return !data.email?.trim();
  }, [data.email]);

  const passwordMissing = useMemo(() => {
    return !data.password?.trim();
  }, [data.password]);

  const handleKeywordDropOutput = useCallback(
    (output: DraggedOutputVariable) => {
      const referenceName = getDroppedOutputReferenceName(
        data.referenced_variables,
        output,
        'value_selector',
      );
      handleUpdateData(
        'referenced_variables',
        upsertNamedSelector(
          data.referenced_variables,
          output,
          'value_selector',
        ),
      );
      return referenceName;
    },
    [data.referenced_variables, handleUpdateData],
  );

  const tokenLabels = useMemo(
    () => getTokenLabelMap(data.referenced_variables, upstreamNodes),
    [data.referenced_variables, upstreamNodes],
  );

  const isCustomProvider = data.provider === 'custom';

  return (
    <div className="flex flex-col gap-2">
      {/* 1. 서버 설정 */}
      <CollapsibleSection title="서버 설정" defaultOpen={true} showDivider>
        <div className="flex flex-col gap-2">
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-gray-700">
              메일 서비스
            </label>
            <RoundedSelect
              value={data.provider || 'gmail'}
              onChange={(val) => handleProviderChange(val as EmailProvider)}
              options={[
                { label: 'Gmail', value: 'gmail' },
                { label: 'Naver', value: 'naver' },
                { label: 'Daum', value: 'daum' },
                { label: 'Outlook', value: 'outlook' },
                { label: '직접 설정', value: 'custom' },
              ]}
              placeholder="메일 서비스 선택"
            />
          </div>

          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-gray-700">
              IMAP 서버
            </label>
            <input
              type="text"
              className={`h-8 w-full rounded border px-2 text-sm focus:outline-none ${
                isCustomProvider
                  ? 'border-gray-300 bg-white focus:border-blue-500'
                  : 'border-gray-200 bg-gray-50 text-gray-600 cursor-not-allowed'
              }`}
              value={data.imap_server || ''}
              onChange={(e) => handleUpdateData('imap_server', e.target.value)}
              readOnly={!isCustomProvider}
              disabled={!isCustomProvider}
            />
          </div>

          <div className="flex gap-2">
            <div className="flex flex-col gap-1 flex-1">
              <label className="text-xs font-medium text-gray-700">포트</label>
              <input
                type="number"
                className={`h-8 w-full rounded border px-2 text-sm focus:outline-none ${
                  isCustomProvider
                    ? 'border-gray-300 bg-white focus:border-blue-500'
                    : 'border-gray-200 bg-gray-50 text-gray-600 cursor-not-allowed'
                }`}
                value={data.imap_port || 993}
                onChange={(e) =>
                  handleUpdateData('imap_port', parseInt(e.target.value))
                }
                readOnly={!isCustomProvider}
                disabled={!isCustomProvider}
              />
            </div>

            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-gray-700">
                SSL 사용
              </label>
              <input
                type="checkbox"
                className="h-8 w-8 rounded border border-gray-300 disabled:cursor-not-allowed disabled:opacity-50"
                checked={data.use_ssl ?? true}
                onChange={(e) => handleUpdateData('use_ssl', e.target.checked)}
                disabled={!isCustomProvider}
              />
            </div>
          </div>

          {isCustomProvider ? (
            <p className="text-[10px] text-gray-500"></p>
          ) : (
            <p className="text-[10px] text-blue-600">
              ℹ️ 메일 서비스 선택 시 서버 설정이 자동으로 구성됩니다
            </p>
          )}
        </div>
      </CollapsibleSection>

      {/* 2. 계정 */}
      <CollapsibleSection title="계정" defaultOpen={true} showDivider>
        <div className="flex flex-col gap-2">
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-gray-700">이메일</label>
            <input
              type="email"
              className="h-8 w-full rounded border border-gray-300 px-2 text-sm focus:outline-none focus:border-blue-500"
              placeholder="your@email.com"
              value={data.email || ''}
              onChange={(e) => handleUpdateData('email', e.target.value)}
            />
            {emailMissing && (
              <ValidationAlert message="⚠️ 이메일을 입력해주세요." />
            )}
          </div>

          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-gray-700">
              비밀번호
            </label>
            <input
              type="password"
              className="h-8 w-full rounded border border-gray-300 px-2 text-sm font-mono focus:outline-none focus:border-blue-500"
              placeholder="앱 비밀번호"
              value={data.password || ''}
              onChange={(e) => handleUpdateData('password', e.target.value)}
            />
            <p className="text-[10px] text-gray-500">
              💡 Gmail: 앱 비밀번호 사용 권장
            </p>
            {passwordMissing && (
              <ValidationAlert message="⚠️ 비밀번호를 입력해주세요." />
            )}
          </div>
        </div>
      </CollapsibleSection>

      {/* 4. 검색 옵션 */}
      <CollapsibleSection title="검색 옵션" defaultOpen={true} showDivider>
        <div className="flex flex-col gap-2 relative">
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-gray-700">
              검색 키워드
            </label>
            <VariableTokenEditor
              className="min-h-20 font-mono text-xs"
              placeholder="검색 키워드를 입력하세요..."
              value={data.keyword || ''}
              onChange={(value) => handleUpdateData('keyword', value)}
              onDropOutput={handleKeywordDropOutput}
              tokenLabels={tokenLabels}
              ariaLabel="메일 검색 키워드"
            />
            <p className="text-[10px] text-gray-500">
              검색 키워드에 커서를 둔 뒤 좌측 입력 패널에서 변수를 클릭해
              추가하세요.
            </p>
          </div>

          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-gray-700">
              보낸 사람
            </label>
            <input
              type="text"
              className="h-8 w-full rounded border border-gray-300 px-2 text-sm focus:outline-none focus:border-blue-500"
              placeholder="예) sender@example.com"
              value={data.sender || ''}
              onChange={(e) => handleUpdateData('sender', e.target.value)}
            />
          </div>

          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-gray-700">제목</label>
            <input
              type="text"
              className="h-8 w-full rounded border border-gray-300 px-2 text-sm focus:outline-none focus:border-blue-500"
              placeholder="메일 제목..."
              value={data.subject || ''}
              onChange={(e) => handleUpdateData('subject', e.target.value)}
            />
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-gray-700">
                시작 날짜
              </label>
              <input
                type="date"
                className="h-8 w-full rounded border border-gray-300 px-2 text-sm focus:outline-none focus:border-blue-500"
                value={data.start_date || ''}
                onChange={(e) => handleUpdateData('start_date', e.target.value)}
              />
              <p className="text-[10px] text-gray-500">💡 기본값: 7일 전</p>
            </div>

            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-gray-700">
                종료 날짜
              </label>
              <input
                type="date"
                className="h-8 w-full rounded border border-gray-300 px-2 text-sm focus:outline-none focus:border-blue-500"
                value={data.end_date || ''}
                onChange={(e) => handleUpdateData('end_date', e.target.value)}
              />
            </div>
          </div>

          {/* 폴더 */}
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-gray-700">폴더</label>
            <RoundedSelect
              value={data.folder || 'INBOX'}
              onChange={(val) => handleUpdateData('folder', val)}
              options={[
                { label: 'INBOX', value: 'INBOX' },
                { label: 'SENT', value: 'SENT' },
                { label: 'DRAFTS', value: 'DRAFTS' },
                { label: 'SPAM', value: 'SPAM' },
                { label: 'TRASH', value: 'TRASH' },
              ]}
              placeholder="폴더 선택"
              className="h-8 py-1"
            />
          </div>

          {/* 최대 결과 수 */}
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-gray-700">
              최대 결과 수
            </label>
            <input
              type="number"
              min="1"
              max="100"
              className="h-8 w-full rounded border border-gray-300 px-2 text-sm focus:outline-none focus:border-blue-500"
              value={data.max_results ?? ''}
              placeholder="5"
              onChange={(e) => {
                const value =
                  e.target.value === '' ? undefined : parseInt(e.target.value);
                handleUpdateData('max_results', value);
              }}
            />
            <p className="text-[10px] text-gray-500">
              💡 기본값: 5 (비어있을 때)
            </p>
          </div>

          {/* 체크박스 */}
          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              id="unread-only"
              className="h-4 w-4 rounded border-gray-300"
              checked={data.unread_only || false}
              onChange={(e) =>
                handleUpdateData('unread_only', e.target.checked)
              }
            />
            <label htmlFor="unread-only" className="text-xs text-gray-700">
              읽지 않은 메일만
            </label>
          </div>

          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              id="mark-as-read"
              className="h-4 w-4 rounded border-gray-300"
              checked={data.mark_as_read || false}
              onChange={(e) =>
                handleUpdateData('mark_as_read', e.target.checked)
              }
            />
            <label htmlFor="mark-as-read" className="text-xs text-gray-700">
              검색 후 읽음 처리
            </label>
          </div>
        </div>
      </CollapsibleSection>
    </div>
  );
}
