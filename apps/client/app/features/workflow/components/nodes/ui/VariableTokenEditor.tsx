import { DragEvent, useEffect, useRef } from 'react';
import Editor from 'react-simple-code-editor';

import {
  DraggedOutputVariable,
  NODE_OUTPUT_DRAG_MIME,
  parseDraggedOutput,
} from '../../../utils/nodeVariablePorts';
import { cn } from '@/lib/utils';

const TOKEN_PATTERN = /{{\s*([^}]+?)\s*}}/g;

const escapeHtml = (value: string) =>
  value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');

const highlightTokens = (
  value: string,
  tokenLabels: Record<string, string> = {},
) => {
  let result = '';
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  TOKEN_PATTERN.lastIndex = 0;

  while ((match = TOKEN_PATTERN.exec(value)) !== null) {
    const key = match[1].trim();
    const label = tokenLabels[key] || key;
    result += escapeHtml(value.slice(lastIndex, match.index));
    result += `<span class="inline-flex max-w-full items-center rounded-md border border-gray-200 bg-gray-50 px-2 py-1 text-xs font-semibold text-gray-800 shadow-sm">${escapeHtml(label)}</span>`;
    lastIndex = match.index + match[0].length;
  }

  result += escapeHtml(value.slice(lastIndex));
  return result;
};

const insertAtSelection = (
  textarea: HTMLTextAreaElement,
  value: string,
  token: string,
) => {
  const selectionStart = textarea.selectionStart ?? value.length;
  const selectionEnd = textarea.selectionEnd ?? selectionStart;
  const nextValue = `${value.slice(0, selectionStart)}${token}${value.slice(selectionEnd)}`;
  const nextCursor = selectionStart + token.length;

  return { nextValue, nextCursor };
};

type VariableTokenEditorProps = {
  value: string;
  onChange: (value: string) => void;
  onDropOutput?: (output: DraggedOutputVariable) => void;
  placeholder?: string;
  className?: string;
  ariaLabel?: string;
  tokenLabels?: Record<string, string>;
};

export const VariableTokenEditor = ({
  value,
  onChange,
  onDropOutput,
  placeholder,
  className,
  ariaLabel,
  tokenLabels,
}: VariableTokenEditorProps) => {
  const wrapperRef = useRef<HTMLDivElement>(null);

  const getTextarea = () =>
    wrapperRef.current?.querySelector('textarea') as HTMLTextAreaElement | null;

  useEffect(() => {
    const textarea = wrapperRef.current?.querySelector('textarea');
    if (!textarea || !ariaLabel) return;
    textarea.setAttribute('aria-label', ariaLabel);
  }, [ariaLabel]);

  const handleDragOver = (event: DragEvent<HTMLDivElement>) => {
    if (!event.dataTransfer.types.includes(NODE_OUTPUT_DRAG_MIME)) return;
    event.preventDefault();
    event.stopPropagation();
    event.dataTransfer.dropEffect = 'copy';
  };

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    const output = parseDraggedOutput(event.dataTransfer);
    if (!output) return;

    event.preventDefault();
    event.stopPropagation();

    const textarea = getTextarea();
    const token = `{{${output.key}}}`;

    if (!textarea) {
      onChange(`${value}${token}`);
      onDropOutput?.(output);
      return;
    }

    const { nextValue, nextCursor } = insertAtSelection(textarea, value, token);
    onChange(nextValue);
    onDropOutput?.(output);

    window.setTimeout(() => {
      textarea.focus();
      textarea.setSelectionRange(nextCursor, nextCursor);
    }, 0);
  };

  return (
    <div
      ref={wrapperRef}
      className={cn(
        'relative rounded border border-gray-300 bg-white text-sm text-gray-800 focus-within:border-blue-500 focus-within:outline-none',
        className,
      )}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
    >
      <Editor
        value={value}
        onValueChange={onChange}
        highlight={(code) => highlightTokens(code, tokenLabels)}
        placeholder={placeholder}
        textareaClassName="focus:outline-none"
        preClassName="break-words whitespace-pre-wrap"
        padding={8}
        aria-label={ariaLabel}
        style={{
          minHeight: 'inherit',
          fontFamily: 'inherit',
          fontSize: 'inherit',
          lineHeight: 1.5,
        }}
      />
    </div>
  );
};
