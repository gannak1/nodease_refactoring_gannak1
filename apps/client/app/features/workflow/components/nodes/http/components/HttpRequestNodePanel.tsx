import { useCallback, useMemo, useState, useRef } from 'react';
import { useWorkflowStore } from '@/app/features/workflow/store/useWorkflowStore';
import { HelpCircle, Plus, Trash2 } from 'lucide-react';
import {
  HttpRequestNodeData,
  HttpMethod,
  AuthType,
} from '../../../../types/Nodes';
import { getUpstreamNodes } from '../../../../utils/getUpstreamNodes';
import { CollapsibleSection } from '../../ui/CollapsibleSection';
import { RoundedSelect } from '../../../ui/RoundedSelect';
import { ValidationAlert } from '../../../ui/ValidationAlert';
import { UnregisteredVariablesAlert } from '../../../ui/UnregisteredVariablesAlert';
import {
  DraggedOutputVariable,
  getDroppedOutputReferenceName,
  getTokenLabelMap,
  upsertNamedSelector,
} from '@/app/features/workflow/utils/nodeVariablePorts';
import { VariableTokenEditor } from '../../ui/VariableTokenEditor';

// 노드 실행 필수 요건 체크
// 1. URL이 입력되어 있어야 함
// 2. GET, DELETE 제외 메서드는 Body가 있어야 함

const getCaretCoordinates = (
  element: HTMLTextAreaElement | HTMLInputElement,
  position: number,
) => {
  const div = document.createElement('div');
  const style = window.getComputedStyle(element);

  // 스타일 복사
  Array.from(style).forEach((prop) => {
    div.style.setProperty(prop, style.getPropertyValue(prop));
  });

  div.style.position = 'absolute';
  div.style.visibility = 'hidden';
  div.style.whiteSpace = 'pre-wrap';
  div.style.top = '0';
  div.style.left = '0';

  // input 태그의 경우 스크롤과 줄바꿈 방지 처리 필요
  if (element.tagName === 'INPUT') {
    div.style.whiteSpace = 'nowrap';
    div.style.overflow = 'hidden';
  }

  const textContent = element.value.substring(0, position);
  div.innerHTML =
    textContent.replace(/\n/g, '<br>') + '<span id="caret-marker">|</span>';

  document.body.appendChild(div);

  const marker = div.querySelector('#caret-marker');
  const coordinates = {
    top: marker
      ? marker.getBoundingClientRect().top - div.getBoundingClientRect().top
      : 0,
    left: marker
      ? marker.getBoundingClientRect().left - div.getBoundingClientRect().left
      : 0,
    height: parseInt(style.lineHeight) || 20,
  };

  document.body.removeChild(div);
  return coordinates;
};

interface HttpRequestNodePanelProps {
  nodeId: string;
  data: HttpRequestNodeData;
}

export function HttpRequestNodePanel({
  nodeId,
  data,
}: HttpRequestNodePanelProps) {
  const { updateNodeData, nodes, edges } = useWorkflowStore();

  // 자동완성을 위한 Refs
  const urlRef = useRef<HTMLTextAreaElement>(null);
  const bodyRef = useRef<HTMLTextAreaElement>(null);

  // 자동완성 상태
  const [activeField, setActiveField] = useState<'url' | 'body' | null>(null);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [suggestionPos, setSuggestionPos] = useState({ top: 0, left: 0 });

  // 상위 노드 가져오기
  const upstreamNodes = useMemo(
    () => getUpstreamNodes(nodeId, nodes, edges),
    [nodeId, nodes, edges],
  );

  const urlMissing = useMemo(() => {
    return !data.url?.trim();
  }, [data.url]);

  const bodyRequiredButMissing = useMemo(() => {
    const method = data.method || 'GET';
    if (method === 'GET' || method === 'DELETE') return false;
    return !data.body?.trim();
  }, [data.method, data.body]);

  const validationErrors = useMemo(() => {
    const allContent = (data.url || '') + (data.body || '');
    const registeredNames = new Set(
      (data.referenced_variables || [])
        .map((v) => v.name?.trim())
        .filter(Boolean),
    );
    const errors: string[] = [];

    const regex = /\{\{\s*([^}]+?)\s*\}\}/g;
    let match;
    while ((match = regex.exec(allContent)) !== null) {
      const varName = match[1].trim();
      if (varName && !registeredNames.has(varName)) {
        errors.push(varName);
      }
    }
    return Array.from(new Set(errors));
  }, [data.url, data.body, data.referenced_variables]);

  const handleUpdateData = useCallback(
    (key: keyof HttpRequestNodeData, value: unknown) => {
      updateNodeData(nodeId, { [key]: value });
    },
    [nodeId, updateNodeData],
  );

  const handleAddHeader = useCallback(() => {
    const newHeaders = [...(data.headers || []), { key: '', value: '' }];
    updateNodeData(nodeId, { headers: newHeaders });
  }, [data.headers, nodeId, updateNodeData]);

  const handleRemoveHeader = useCallback(
    (index: number) => {
      const newHeaders = [...(data.headers || [])];
      newHeaders.splice(index, 1);
      updateNodeData(nodeId, { headers: newHeaders });
    },
    [data.headers, nodeId, updateNodeData],
  );

  const handleUpdateHeader = useCallback(
    (index: number, key: 'key' | 'value', value: string) => {
      const newHeaders = [...(data.headers || [])];
      newHeaders[index] = { ...newHeaders[index], [key]: value };
      updateNodeData(nodeId, { headers: newHeaders });
    },
    [data.headers, nodeId, updateNodeData],
  );

  const handleTextDropOutput = useCallback(
    (output: DraggedOutputVariable) => {
      const referenceName = getDroppedOutputReferenceName(
        data.referenced_variables,
        output,
        'value_selector',
      );
      updateNodeData(nodeId, {
        referenced_variables: upsertNamedSelector(
          data.referenced_variables,
          output,
          'value_selector',
        ),
      });
      return referenceName;
    },
    [data.referenced_variables, nodeId, updateNodeData],
  );

  const tokenLabels = useMemo(
    () => getTokenLabelMap(data.referenced_variables, upstreamNodes),
    [data.referenced_variables, upstreamNodes],
  );

  // 자동완성 핸들러
  const handleKeyUp = (
    e: React.KeyboardEvent<HTMLTextAreaElement | HTMLInputElement>,
    field: 'url' | 'body',
  ) => {
    const target = e.target as HTMLTextAreaElement | HTMLInputElement;
    const value = target.value;
    const selectionEnd = target.selectionEnd || 0;

    setActiveField(field);

    if (value.substring(selectionEnd - 2, selectionEnd) === '{{') {
      const coords = getCaretCoordinates(target, selectionEnd);

      setSuggestionPos({
        top: target.offsetTop + coords.top + coords.height,
        left: target.offsetLeft + coords.left,
      });
      setShowSuggestions(true);
    } else {
      setShowSuggestions(false);
    }
  };

  const insertVariable = (varName: string) => {
    if (!activeField) return;

    const currentValue =
      activeField === 'url' ? data.url || '' : data.body || '';
    const ref = activeField === 'url' ? urlRef : bodyRef;
    const input = ref.current;

    if (!input) return;

    const selectionEnd = input.selectionEnd || 0;
    const lastOpen = currentValue.lastIndexOf('{{', selectionEnd);

    if (lastOpen !== -1) {
      const prefix = currentValue.substring(0, lastOpen);
      const suffix = currentValue.substring(selectionEnd);

      const newValue = `${prefix}{{ ${varName} }}${suffix}`;

      handleUpdateData(activeField, newValue);
      setShowSuggestions(false);

      setTimeout(() => {
        const newCursorPos = prefix.length + varName.length + 5;
        input.focus();
        input.setSelectionRange(newCursorPos, newCursorPos);
      }, 0);
    }
  };

  return (
    <div className="flex flex-col gap-2 relative">
      {/* 1. 메서드 & URL */}
      <div className="flex gap-2">
        <div className="w-24 flex-shrink-0">
          <RoundedSelect
            value={data.method || 'GET'}
            onChange={(val) => handleUpdateData('method', val as HttpMethod)}
            options={[
              { label: 'GET', value: 'GET' },
              { label: 'POST', value: 'POST' },
              { label: 'PUT', value: 'PUT' },
              { label: 'DELETE', value: 'DELETE' },
              { label: 'PATCH', value: 'PATCH' },
            ]}
            placeholder="Method"
          />
        </div>

        <textarea
          ref={urlRef}
          className="flex-1 rounded-md border border-gray-300 px-3 py-[7px] text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 font-mono resize-none transition-all duration-200 h-9 focus:h-20 overflow-hidden focus:overflow-auto leading-[22px]"
          placeholder="https://api.example.com/v1/resource"
          value={data.url || ''}
          onChange={(e) => handleUpdateData('url', e.target.value)}
          onKeyUp={(e) => handleKeyUp(e, 'url')}
          autoComplete="off"
          data-variable-drop-enabled="true"
          data-variable-drop-field="url"
          rows={1}
        />
      </div>

      {urlMissing && <ValidationAlert message="⚠️ URL을 입력해주세요." />}

      <div className="border-b border-gray-200" />

      <CollapsibleSection title="인증" showDivider>
        <div className="flex flex-col gap-3">
          <div className="flex items-center gap-2">
            <RoundedSelect
              value={data.authType || 'none'}
              onChange={(val) => handleUpdateData('authType', val as AuthType)}
              options={[
                { label: '인증 없음', value: 'none' },
                { label: 'Bearer Token', value: 'bearer' },
                { label: 'API Key', value: 'apiKey' },
              ]}
              placeholder="인증 방식 선택"
            />
          </div>

          {data.authType === 'bearer' && (
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-gray-700">토큰</label>
              <input
                className="w-full h-8 rounded border border-gray-300 px-2 text-sm font-mono focus:outline-none focus:border-blue-500"
                placeholder="예) eyJhbGciOiJIUzI1Ni..."
                value={data.authConfig?.token || ''}
                onChange={(e) =>
                  handleUpdateData('authConfig', {
                    ...data.authConfig,
                    token: e.target.value,
                  })
                }
              />
              <p className="text-[10px] text-gray-400">
                예: Authorization: Bearer {'{token}'}
              </p>
            </div>
          )}

          {data.authType === 'apiKey' && (
            <div className="flex flex-col gap-3">
              <div className="flex flex-col gap-1">
                <label className="text-xs font-medium text-gray-700">
                  헤더 이름
                </label>
                <input
                  className="w-full h-8 rounded border border-gray-300 px-2 text-sm font-mono focus:outline-none focus:border-blue-500"
                  placeholder="예) X-API-Key"
                  value={data.authConfig?.apiKeyHeader || 'X-API-Key'}
                  onChange={(e) =>
                    handleUpdateData('authConfig', {
                      ...data.authConfig,
                      apiKeyHeader: e.target.value,
                    })
                  }
                />
              </div>
              <div className="flex flex-col gap-1">
                <label className="text-xs font-medium text-gray-700">
                  API Key
                </label>
                <input
                  className="w-full h-8 rounded border border-gray-300 px-2 text-sm font-mono focus:outline-none focus:border-blue-500"
                  placeholder="예) my-secret-key-123"
                  value={data.authConfig?.apiKeyValue || ''}
                  onChange={(e) =>
                    handleUpdateData('authConfig', {
                      ...data.authConfig,
                      apiKeyValue: e.target.value,
                    })
                  }
                />
              </div>
            </div>
          )}
        </div>
      </CollapsibleSection>

      {/* 3. 헤더 */}
      <CollapsibleSection
        title="헤더"
        showDivider
        icon={(expand) => (
          <button
            onClick={(e) => {
              e.stopPropagation();
              expand(); // 섹션 펼치기
              handleAddHeader();
            }}
            className="p-1 hover:bg-gray-200 rounded transition-colors"
            title="헤더 추가"
          >
            <Plus className="w-3.5 h-3.5 text-gray-600" />
          </button>
        )}
      >
        <div className="flex flex-col gap-2">
          {data.headers?.map((header, index) => (
            <div key={index} className="flex gap-2 items-center">
              <input
                className="h-8 w-1/3 rounded border border-gray-300 px-2 text-xs font-mono focus:outline-none focus:border-blue-500"
                placeholder="키"
                value={header.key}
                onChange={(e) =>
                  handleUpdateHeader(index, 'key', e.target.value)
                }
              />
              <input
                className="h-8 flex-1 rounded border border-gray-300 px-2 text-xs font-mono focus:outline-none focus:border-blue-500"
                placeholder="값"
                value={header.value}
                onChange={(e) =>
                  handleUpdateHeader(index, 'value', e.target.value)
                }
              />
              <button
                className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded"
                onClick={() => handleRemoveHeader(index)}
                title="삭제"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
          ))}
          {(!data.headers || data.headers.length === 0) && (
            <div className="text-center text-xs text-gray-400 py-2 border border-dashed border-gray-200 rounded">
              추가된 헤더가 없습니다.
            </div>
          )}

          <div className="text-[10px] text-blue-600 bg-blue-50 p-2 rounded">
            헤더를 비워두면 Body가 있는 경우 <code>application/json</code>이
            자동 추가됩니다.
          </div>
        </div>
      </CollapsibleSection>

      {/* 4. 본문 (POST/PUT/PATCH 전용) */}
      {['POST', 'PUT', 'PATCH'].includes(data.method || '') && (
        <CollapsibleSection title="본문" showDivider>
          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <span className="text-xs text-gray-500">Content-Type: JSON</span>
            </div>
            <VariableTokenEditor
              className="min-h-32 font-mono text-xs"
              placeholder='{"key": "value"}'
              value={data.body || ''}
              onChange={(value) => handleUpdateData('body', value)}
              onDropOutput={handleTextDropOutput}
              tokenLabels={tokenLabels}
              ariaLabel="HTTP Body"
            />
            <div className="text-[10px] text-gray-500">
              💡 <code>{'{{variable}}'}</code> 문법 사용 가능
            </div>

            {bodyRequiredButMissing && (
              <ValidationAlert
                message={`⚠️ ${data.method || 'POST'} 요청에는 본문(Body)이 필요합니다.`}
              />
            )}
          </div>
        </CollapsibleSection>
      )}

      {/* 5. 설정 (타임아웃) */}
      <CollapsibleSection title="설정" defaultOpen={false} showDivider>
        <div className="flex flex-col gap-1">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1">
              <label className="text-xs font-medium text-gray-700">
                타임아웃 (ms)
              </label>
              <div className="group relative inline-block">
                <HelpCircle className="h-3.5 w-3.5 text-gray-400 cursor-help" />
                <div className="absolute z-50 hidden group-hover:block w-56 p-2 text-[11px] text-gray-600 bg-white border border-gray-200 rounded-lg shadow-lg left-0 top-5">
                  요청이 이 시간 내에 끝나지 않으면 자동으로 실패 처리됩니다.
                  <div className="absolute -top-1 left-2 w-2 h-2 bg-white border-l border-t border-gray-200 rotate-45" />
                </div>
              </div>
            </div>
            <input
              type="number"
              className="w-24 h-8 px-2 text-sm text-right border border-gray-300 rounded focus:outline-none focus:border-blue-500"
              placeholder="5000"
              value={data.timeout || 5000}
              onChange={(e) =>
                handleUpdateData('timeout', parseInt(e.target.value) || 0)
              }
            />
          </div>
        </div>
      </CollapsibleSection>

      {/* 자동완성 제안 드롭다운 */}
      {/* [VALIDATION] 경고 영역 */}

      {validationErrors.length > 0 && (
        <UnregisteredVariablesAlert variables={validationErrors} />
      )}

      {showSuggestions && (
        <div
          className="absolute z-50 w-48 rounded border border-gray-200 bg-white shadow-lg"
          style={{
            top: suggestionPos.top,
            left: suggestionPos.left,
          }}
        >
          {(data.referenced_variables || []).length > 0 ? (
            (data.referenced_variables || []).map((v, i) => (
              <button
                key={i}
                className="block w-full px-4 py-2 text-left text-sm hover:bg-gray-100"
                onClick={() => insertVariable(v.name)}
              >
                {v.name || '(이름 없음)'}
              </button>
            ))
          ) : (
            <div className="px-4 py-2 text-sm text-gray-400">
              등록된 입력변수가 없습니다.
            </div>
          )}
        </div>
      )}
    </div>
  );
}
