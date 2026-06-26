import {
  DragEvent,
  KeyboardEvent,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from 'react';

import {
  DraggedOutputVariable,
  NODE_OUTPUT_DRAG_MIME,
  parseDraggedOutput,
} from '../../../utils/nodeVariablePorts';
import { cn } from '@/lib/utils';

const TOKEN_PATTERN = /{{\s*([^}]+?)\s*}}/g;
const TOKEN_ATTR = 'data-variable-token';
const TOKEN_NAME_ATTR = 'data-variable-name';

type Segment =
  | { type: 'text'; value: string }
  | { type: 'variable'; name: string; label: string };

const parseValueToSegments = (
  value: string,
  tokenLabels: Record<string, string> = {},
): Segment[] => {
  const segments: Segment[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  TOKEN_PATTERN.lastIndex = 0;

  while ((match = TOKEN_PATTERN.exec(value)) !== null) {
    if (match.index > lastIndex) {
      segments.push({ type: 'text', value: value.slice(lastIndex, match.index) });
    }

    const name = match[1].trim();
    segments.push({
      type: 'variable',
      name,
      label: tokenLabels[name] || name,
    });
    lastIndex = match.index + match[0].length;
  }

  if (lastIndex < value.length) {
    segments.push({ type: 'text', value: value.slice(lastIndex) });
  }

  return segments;
};

const createTextNode = (text: string) => document.createTextNode(text);

const createTokenNode = (name: string, label: string) => {
  const span = document.createElement('span');
  span.setAttribute(TOKEN_ATTR, 'true');
  span.setAttribute(TOKEN_NAME_ATTR, name);
  span.setAttribute('contenteditable', 'false');
  span.className =
    'mx-0.5 inline-flex max-w-full select-none items-center rounded-md border border-blue-100 bg-blue-50 px-2 py-0.5 text-xs font-semibold text-blue-800 shadow-sm align-baseline';
  span.textContent = label;
  return span;
};

const isTokenElement = (node: Node | null): node is HTMLElement =>
  node instanceof HTMLElement && node.getAttribute(TOKEN_ATTR) === 'true';

const tokenToText = (node: HTMLElement) =>
  `{{${node.getAttribute(TOKEN_NAME_ATTR) || node.textContent || ''}}}`;

const serializeNode = (node: Node): string => {
  if (node.nodeType === Node.TEXT_NODE) return node.textContent || '';
  if (isTokenElement(node)) return tokenToText(node);
  return Array.from(node.childNodes).map(serializeNode).join('');
};

const serializeEditor = (editor: HTMLElement) =>
  Array.from(editor.childNodes).map(serializeNode).join('');

const isEditorEmpty = (editor: HTMLElement) => serializeEditor(editor).length === 0;

const renderSegments = (
  editor: HTMLElement,
  value: string,
  tokenLabels: Record<string, string> = {},
) => {
  editor.replaceChildren();

  const segments = parseValueToSegments(value, tokenLabels);
  if (segments.length === 0) {
    editor.appendChild(createTextNode(''));
    return;
  }

  for (const segment of segments) {
    if (segment.type === 'text') {
      editor.appendChild(createTextNode(segment.value));
    } else {
      editor.appendChild(createTokenNode(segment.name, segment.label));
    }
  }
};

const getActiveRange = (editor: HTMLElement) => {
  const selection = window.getSelection();
  if (!selection || selection.rangeCount === 0) return null;

  const range = selection.getRangeAt(0);
  const container = range.commonAncestorContainer;
  if (!editor.contains(container)) return null;
  return range;
};

const placeCaretAfter = (node: Node) => {
  const range = document.createRange();
  const selection = window.getSelection();
  range.setStartAfter(node);
  range.collapse(true);
  selection?.removeAllRanges();
  selection?.addRange(range);
};

const placeCaretBefore = (node: Node) => {
  const range = document.createRange();
  const selection = window.getSelection();
  range.setStartBefore(node);
  range.collapse(true);
  selection?.removeAllRanges();
  selection?.addRange(range);
};

const selectRange = (range: Range) => {
  const selection = window.getSelection();
  selection?.removeAllRanges();
  selection?.addRange(range);
};

const getTokenAtRange = (editor: HTMLElement, range: Range) => {
  const container =
    range.commonAncestorContainer.nodeType === Node.ELEMENT_NODE
      ? (range.commonAncestorContainer as HTMLElement)
      : range.commonAncestorContainer.parentElement;
  const token = container?.closest(`[${TOKEN_ATTR}="true"]`);
  return token && editor.contains(token) ? token : null;
};

const getPointRange = (
  editor: HTMLElement,
  clientX: number,
  clientY: number,
): Range | null => {
  const documentWithCaretPosition = document as Document & {
    caretPositionFromPoint?: (
      x: number,
      y: number,
    ) => { offsetNode: Node; offset: number } | null;
  };

  const range = document.caretRangeFromPoint?.(clientX, clientY);
  if (range && editor.contains(range.commonAncestorContainer)) {
    const token = getTokenAtRange(editor, range);

    if (token && editor.contains(token)) {
      const tokenRange = document.createRange();
      const tokenRect = token.getBoundingClientRect();
      if (clientX < tokenRect.left + tokenRect.width / 2) {
        tokenRange.setStartBefore(token);
      } else {
        tokenRange.setStartAfter(token);
      }
      tokenRange.collapse(true);
      return tokenRange;
    }

    range.collapse(true);
    return range;
  }

  const position = documentWithCaretPosition.caretPositionFromPoint?.(
    clientX,
    clientY,
  );
  if (position && editor.contains(position.offsetNode)) {
    const nextRange = document.createRange();
    nextRange.setStart(position.offsetNode, position.offset);
    nextRange.collapse(true);
    return nextRange;
  }

  const rect = editor.getBoundingClientRect();
  if (
    clientX < rect.left ||
    clientX > rect.right ||
    clientY < rect.top ||
    clientY > rect.bottom
  ) {
    return null;
  }

  const fallbackRange = document.createRange();
  const isBeforeFirstLine = clientY < rect.top + rect.height / 2;
  if (isBeforeFirstLine && editor.firstChild) {
    fallbackRange.setStartBefore(editor.firstChild);
  } else if (editor.lastChild) {
    fallbackRange.setStartAfter(editor.lastChild);
  } else {
    fallbackRange.selectNodeContents(editor);
  }
  fallbackRange.collapse(true);
  return fallbackRange;
};

const insertNodeAtRange = (
  editor: HTMLElement,
  node: Node,
  range: Range | null,
) => {
  editor.focus();
  const targetRange = range || getActiveRange(editor);

  if (!targetRange) {
    editor.appendChild(node);
    placeCaretAfter(node);
    return;
  }

  targetRange.deleteContents();
  targetRange.insertNode(node);
  placeCaretAfter(node);
};

const insertNodeAtSelection = (editor: HTMLElement, node: Node) => {
  insertNodeAtRange(editor, node, getActiveRange(editor));
};

const getAdjacentToken = (
  editor: HTMLElement,
  direction: 'backward' | 'forward',
) => {
  const range = getActiveRange(editor);
  if (!range || !range.collapsed) return null;

  const { startContainer, startOffset } = range;

  if (startContainer.nodeType === Node.TEXT_NODE) {
    const textLength = startContainer.textContent?.length || 0;
    if (direction === 'backward' && startOffset > 0) return null;
    if (direction === 'forward' && startOffset < textLength) return null;

    const sibling =
      direction === 'backward'
        ? startContainer.previousSibling
        : startContainer.nextSibling;
    return isTokenElement(sibling) ? sibling : null;
  }

  if (startContainer === editor) {
    const index = direction === 'backward' ? startOffset - 1 : startOffset;
    const child = editor.childNodes[index];
    return isTokenElement(child) ? child : null;
  }

  const element =
    startContainer.nodeType === Node.ELEMENT_NODE
      ? (startContainer as HTMLElement)
      : startContainer.parentElement;
  if (!element || !editor.contains(element)) return null;

  const sibling =
    direction === 'backward' ? element.previousSibling : element.nextSibling;
  return isTokenElement(sibling) ? sibling : null;
};

const moveCaretAwayFromToken = (editor: HTMLElement) => {
  const range = getActiveRange(editor);
  if (!range) return;

  const container =
    range.startContainer.nodeType === Node.ELEMENT_NODE
      ? (range.startContainer as HTMLElement)
      : range.startContainer.parentElement;

  const token = container?.closest(`[${TOKEN_ATTR}="true"]`);
  if (!token || !editor.contains(token)) return;
  placeCaretAfter(token);
};

type VariableTokenEditorProps = {
  value: string;
  onChange: (value: string) => void;
  onDropOutput?: (output: DraggedOutputVariable) => string | void;
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
  tokenLabels = {},
}: VariableTokenEditorProps) => {
  const editorRef = useRef<HTMLDivElement>(null);
  const lastRenderedValueRef = useRef<string | null>(null);
  const lastTokenLabelsRef = useRef('');
  const composingRef = useRef(false);
  const [isEmpty, setIsEmpty] = useState(!value);

  const syncPlaceholder = () => {
    const editor = editorRef.current;
    if (!editor) return;
    setIsEmpty(isEditorEmpty(editor));
  };

  const emitChange = () => {
    const editor = editorRef.current;
    if (!editor) return;

    const nextValue = serializeEditor(editor);
    lastRenderedValueRef.current = nextValue;
    syncPlaceholder();
    onChange(nextValue);
  };

  useLayoutEffect(() => {
    const editor = editorRef.current;
    if (!editor) return;

    const currentValue = serializeEditor(editor);
    const tokenLabelsSignature = JSON.stringify(tokenLabels);
    const shouldRender =
      lastRenderedValueRef.current === null ||
      lastTokenLabelsRef.current !== tokenLabelsSignature ||
      (value !== lastRenderedValueRef.current && value !== currentValue);

    if (shouldRender) {
      renderSegments(editor, value, tokenLabels);
      syncPlaceholder();
    }

    lastRenderedValueRef.current = value;
    lastTokenLabelsRef.current = tokenLabelsSignature;
  }, [value, tokenLabels]);

  useEffect(() => {
    syncPlaceholder();
  }, []);

  const handleDragOver = (event: DragEvent<HTMLDivElement>) => {
    if (!event.dataTransfer.types.includes(NODE_OUTPUT_DRAG_MIME)) return;
    event.preventDefault();
    event.stopPropagation();
    event.dataTransfer.dropEffect = 'copy';
  };

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    const output = parseDraggedOutput(event.dataTransfer);
    const editor = editorRef.current;
    if (!output || !editor) return;

    event.preventDefault();
    event.stopPropagation();

    const droppedName = onDropOutput?.(output) || output.key;
    const label = tokenLabels[droppedName] || output.label || droppedName;
    const tokenNode = createTokenNode(droppedName, label);

    editor.focus();

    const dropRange = getPointRange(editor, event.clientX, event.clientY);
    if (dropRange) selectRange(dropRange);

    insertNodeAtRange(editor, tokenNode, dropRange);
    emitChange();
  };

  const handleInput = () => {
    if (composingRef.current) return;
    emitChange();
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const editor = editorRef.current;
    if (!editor) return;

    if (event.key === 'Backspace') {
      const token = getAdjacentToken(editor, 'backward');
      if (!token) return;
      event.preventDefault();
      const previous = token.previousSibling;
      token.remove();
      if (previous) placeCaretAfter(previous);
      emitChange();
      return;
    }

    if (event.key === 'Delete') {
      const token = getAdjacentToken(editor, 'forward');
      if (!token) return;
      event.preventDefault();
      const next = token.nextSibling;
      token.remove();
      if (next) placeCaretBefore(next);
      emitChange();
      return;
    }

    if (event.key === 'Enter') {
      event.preventDefault();
      insertNodeAtSelection(editor, createTextNode('\n'));
      emitChange();
    }
  };

  const handlePaste = (event: React.ClipboardEvent<HTMLDivElement>) => {
    const editor = editorRef.current;
    if (!editor) return;

    event.preventDefault();
    const text = event.clipboardData.getData('text/plain');
    insertNodeAtSelection(editor, createTextNode(text));
    emitChange();
  };

  return (
    <div
      className={cn(
        'relative rounded border border-gray-300 bg-white text-sm text-gray-800 focus-within:border-blue-500 focus-within:outline-none',
        className,
      )}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
    >
      {placeholder && (
        <div
          className={cn(
            'pointer-events-none absolute left-2 top-2 whitespace-pre-wrap text-sm leading-6 text-gray-400',
            !isEmpty && 'hidden',
          )}
        >
          {placeholder}
        </div>
      )}
      <div
        ref={editorRef}
        role="textbox"
        aria-label={ariaLabel}
        aria-multiline="true"
        contentEditable
        suppressContentEditableWarning
        className="min-h-[inherit] whitespace-pre-wrap break-words px-2 py-2 leading-6 outline-none"
        onBlur={() => {
          const editor = editorRef.current;
          if (editor) moveCaretAwayFromToken(editor);
        }}
        onCompositionEnd={() => {
          composingRef.current = false;
          emitChange();
        }}
        onCompositionStart={() => {
          composingRef.current = true;
        }}
        onInput={handleInput}
        onKeyDown={handleKeyDown}
        onPaste={handlePaste}
      />
    </div>
  );
};
