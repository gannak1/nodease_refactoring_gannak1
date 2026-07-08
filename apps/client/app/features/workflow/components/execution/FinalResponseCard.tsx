import { useId } from 'react';
import { MessageSquare } from 'lucide-react';

import type { FinalResponsePreview } from '../../utils/testExecutionFinalResponse';

export function FinalResponseCard({
  preview,
}: {
  preview: FinalResponsePreview;
}) {
  const titleId = useId();

  return (
    <section
      aria-labelledby={titleId}
      className="rounded-lg border border-emerald-200 bg-emerald-50 p-4 dark:border-emerald-800 dark:bg-emerald-900/20"
    >
      <div className="flex items-start gap-3">
        <div className="rounded-md bg-emerald-100 p-2 text-emerald-700 dark:bg-emerald-900/50 dark:text-emerald-200">
          <MessageSquare className="h-4 w-4" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3
              id={titleId}
              className="text-sm font-semibold text-emerald-950 dark:text-emerald-50"
            >
              최종 응답
            </h3>
            <span className="rounded-full border border-emerald-200 bg-white px-2 py-0.5 text-xs text-emerald-700 dark:border-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-200">
              {preview.sourceLabel}
            </span>
          </div>

          {preview.isEmpty ? (
            <p className="mt-3 text-sm text-emerald-700 dark:text-emerald-200">
              최종 사용자에게 표시할 응답이 비어 있습니다.
            </p>
          ) : preview.kind === 'json' ? (
            <div className="mt-3 max-h-56 overflow-y-auto rounded-md border border-emerald-200 bg-white p-3 dark:border-emerald-800 dark:bg-emerald-950/40">
              {preview.items.length > 0 ? (
                <dl className="space-y-2">
                  {preview.items.map((item) => (
                    <div key={item.label} className="min-w-0">
                      <dt className="text-xs font-semibold text-emerald-700 dark:text-emerald-200">
                        {item.label}
                      </dt>
                      <dd className="mt-0.5 whitespace-pre-wrap break-words text-sm text-gray-900 dark:text-gray-100">
                        {item.value}
                      </dd>
                    </div>
                  ))}
                </dl>
              ) : (
                <p className="text-sm text-emerald-700 dark:text-emerald-200">
                  표시 가능한 응답 필드가 없습니다.
                </p>
              )}
            </div>
          ) : (
            <div className="mt-3 max-h-56 overflow-y-auto rounded-md border border-emerald-200 bg-white p-3 dark:border-emerald-800 dark:bg-emerald-950/40">
              <p className="whitespace-pre-wrap break-words text-sm leading-6 text-gray-900 dark:text-gray-100">
                {preview.text}
              </p>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
