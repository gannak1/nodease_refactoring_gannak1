import { useId } from 'react';
import { MessageSquare } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import type { FinalResponsePreview } from '../../utils/testExecutionFinalResponse';

export function FinalResponseCard({
  preview,
  expandContent = false,
  renderMarkdown = false,
  large = false,
}: {
  preview: FinalResponsePreview;
  expandContent?: boolean;
  renderMarkdown?: boolean;
  large?: boolean;
}) {
  const titleId = useId();
  const responseContainerClassName = `${large ? 'mt-4 rounded-lg p-5' : 'mt-3 rounded-md p-3'} border border-emerald-200 bg-white dark:border-emerald-800 dark:bg-emerald-950/40${
    expandContent ? '' : ' max-h-56 overflow-y-auto'
  }`;

  return (
    <section
      aria-labelledby={titleId}
      className={`${large ? 'rounded-xl p-6' : 'rounded-lg p-4'} border border-emerald-200 bg-emerald-50 dark:border-emerald-800 dark:bg-emerald-900/20`}
    >
      <div className={`flex items-start ${large ? 'gap-4' : 'gap-3'}`}>
        <div
          className={`${large ? 'rounded-lg p-3' : 'rounded-md p-2'} bg-emerald-100 text-emerald-700 dark:bg-emerald-900/50 dark:text-emerald-200`}
        >
          <MessageSquare className={large ? 'h-6 w-6' : 'h-4 w-4'} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3
              id={titleId}
              className={`${large ? 'text-xl' : 'text-sm'} font-semibold text-emerald-950 dark:text-emerald-50`}
            >
              최종 응답
            </h3>
            <span
              className={`${large ? 'px-3 py-1 text-base' : 'px-2 py-0.5 text-xs'} rounded-full border border-emerald-200 bg-white text-emerald-700 dark:border-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-200`}
            >
              {preview.sourceLabel}
            </span>
          </div>

          {preview.isEmpty ? (
            <p
              className={`${large ? 'mt-4 text-lg' : 'mt-3 text-sm'} text-emerald-700 dark:text-emerald-200`}
            >
              최종 사용자에게 표시할 응답이 비어 있습니다.
            </p>
          ) : preview.kind === 'json' ? (
            <div className={responseContainerClassName}>
              {preview.items.length > 0 ? (
                <dl className="space-y-2">
                  {preview.items.map((item) => (
                    <div key={item.label} className="min-w-0">
                      <dt
                        className={`${large ? 'text-base' : 'text-xs'} font-semibold text-emerald-700 dark:text-emerald-200`}
                      >
                        {item.label}
                      </dt>
                      <dd
                        className={`${large ? 'mt-1 text-lg leading-8' : 'mt-0.5 text-sm'} whitespace-pre-wrap break-words text-gray-900 dark:text-gray-100`}
                      >
                        {item.value}
                      </dd>
                    </div>
                  ))}
                </dl>
              ) : (
                <p
                  className={`${large ? 'text-lg' : 'text-sm'} text-emerald-700 dark:text-emerald-200`}
                >
                  표시 가능한 응답 필드가 없습니다.
                </p>
              )}
            </div>
          ) : renderMarkdown ? (
            <div
              className={`${responseContainerClassName} ${large ? 'text-lg leading-8' : 'text-sm leading-6'}`}
            >
              <ReactMarkdown
                disallowedElements={['img']}
                remarkPlugins={[remarkGfm]}
                components={{
                  h1: ({ children }) => (
                    <h1 className="mb-4 mt-6 text-2xl font-bold first:mt-0">
                      {children}
                    </h1>
                  ),
                  h2: ({ children }) => (
                    <h2 className="mb-3 mt-6 text-xl font-bold first:mt-0">
                      {children}
                    </h2>
                  ),
                  h3: ({ children }) => (
                    <h3 className="mb-2 mt-5 text-lg font-bold first:mt-0">
                      {children}
                    </h3>
                  ),
                  p: ({ children }) => (
                    <p className="mb-4 break-words last:mb-0">{children}</p>
                  ),
                  ul: ({ children }) => (
                    <ul className="mb-4 list-disc space-y-2 pl-7 last:mb-0">
                      {children}
                    </ul>
                  ),
                  ol: ({ children }) => (
                    <ol className="mb-4 list-decimal space-y-2 pl-7 last:mb-0">
                      {children}
                    </ol>
                  ),
                  blockquote: ({ children }) => (
                    <blockquote className="my-4 border-l-4 border-emerald-300 pl-4 text-slate-600">
                      {children}
                    </blockquote>
                  ),
                  code: ({ children }) => (
                    <code className="break-words rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[0.9em] text-slate-900">
                      {children}
                    </code>
                  ),
                  a: ({ children, href }) => (
                    <a
                      href={href}
                      className="font-semibold text-emerald-700 underline underline-offset-4"
                      rel="noreferrer"
                      target="_blank"
                    >
                      {children}
                    </a>
                  ),
                  table: ({ children }) => (
                    <table className="my-4 w-full border-collapse text-left">
                      {children}
                    </table>
                  ),
                  th: ({ children }) => (
                    <th className="border border-slate-300 bg-slate-50 px-3 py-2 font-semibold">
                      {children}
                    </th>
                  ),
                  td: ({ children }) => (
                    <td className="border border-slate-300 px-3 py-2">
                      {children}
                    </td>
                  ),
                }}
              >
                {preview.text}
              </ReactMarkdown>
            </div>
          ) : (
            <div className={responseContainerClassName}>
              <p
                className={`${large ? 'text-lg leading-8' : 'text-sm leading-6'} whitespace-pre-wrap break-words text-gray-900 dark:text-gray-100`}
              >
                {preview.text}
              </p>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
