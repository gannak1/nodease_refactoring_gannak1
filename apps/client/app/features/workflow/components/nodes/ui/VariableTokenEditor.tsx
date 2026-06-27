import {
  DragEvent,
  KeyboardEvent,
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
} from 'react';
import { createPortal } from 'react-dom';

import {
  DraggedOutputVariable,
  NODE_OUTPUT_DRAG_MIME,
  parseDraggedOutput,
} from '../../../utils/nodeVariablePorts';
import { cn } from '@/lib/utils';
import { useVariableInsertion } from './useVariableInsertion';

const TOKEN_PATTERN = /{{\s*([^}]+?)\s*}}/g;
const TOKEN_ATTR = 'data-variable-token';
const TOKEN_NAME_ATTR = 'data-variable-name';
const TOKEN_INTERNAL_DRAG_MIME = 'application/x-moduly-variable-token';

type Segment =
  | { type: 'text'; value: string }
  | { type: 'variable'; name: string; label: string };

type DropCaret = {
  left: number;
  top: number;
  height: number;
};

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
      segments.push({
        type: 'text',
        value: value.slice(lastIndex, match.index),
      });
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
  span.setAttribute('draggable', 'true');
  span.className =
    'mx-0.5 inline-flex max-w-full cursor-grab select-none items-center rounded-md border border-blue-100 bg-blue-50 px-2 py-0.5 text-xs font-semibold text-blue-800 shadow-sm align-baseline active:cursor-grabbing';
  span.textContent = label;
  return span;
};

const createTokenDragPreview = (label: string) => {
  const preview = document.createElement('span');
  preview.className =
    'inline-flex items-center rounded-md border border-blue-200 bg-blue-50 px-2 py-0.5 text-xs font-semibold text-blue-800 shadow-md';
  preview.textContent = label;
  preview.style.position = 'fixed';
  preview.style.top = '0';
  preview.style.left = '0';
  preview.style.zIndex = '-1';
  preview.style.opacity = '0.99';
  preview.style.pointerEvents = 'none';
  document.body.appendChild(preview);
  return preview;
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

const isEditorEmpty = (editor: HTMLElement) =>
  serializeEditor(editor).length === 0;

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

const getRangeCaret = (
  editor: HTMLElement,
  range: Range | null,
): DropCaret | null => {
  if (!range) return null;

  const rect = range.getClientRects()[0] || range.getBoundingClientRect();

  if (range.startContainer === editor) {
    const nextChild = editor.childNodes[range.startOffset];
    const previousChild = editor.childNodes[range.startOffset - 1];
    const adjacentToken = isTokenElement(nextChild)
      ? { token: nextChild, side: 'left' as const }
      : isTokenElement(previousChild)
        ? { token: previousChild, side: 'right' as const }
        : null;

    if (adjacentToken) {
      const tokenRect = adjacentToken.token.getBoundingClientRect();
      return {
        left: adjacentToken.side === 'left' ? tokenRect.left : tokenRect.right,
        top: tokenRect.top,
        height: tokenRect.height,
      };
    }
  }

  if (rect && rect.height > 0) {
    return {
      left: rect.left,
      top: rect.top,
      height: rect.height,
    };
  }

  const token = getTokenAtRange(editor, range);
  if (token) {
    const tokenRect = token.getBoundingClientRect();
    const isBeforeToken =
      range.startContainer === editor &&
      editor.childNodes[range.startOffset] === token;

    return {
      left: isBeforeToken ? tokenRect.left : tokenRect.right,
      top: tokenRect.top,
      height: tokenRect.height,
    };
  }

  const editorRect = editor.getBoundingClientRect();
  const lineHeight = 24;
  return {
    left: editorRect.left + 8,
    top: editorRect.top + 8,
    height: lineHeight,
  };
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

const isNoopTokenMove = (
  editor: HTMLElement,
  token: HTMLElement,
  range: Range | null,
) => {
  if (!range || range.startContainer !== editor) return false;

  const tokenIndex = Array.from(editor.childNodes).indexOf(token);
  return (
    range.startOffset === tokenIndex || range.startOffset === tokenIndex + 1
  );
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

const getCharacterBeforeRange = (editor: HTMLElement, range: Range) => {
  const { startContainer, startOffset } = range;

  if (startContainer.nodeType === Node.TEXT_NODE) {
    return startContainer.textContent?.[startOffset - 1] || '';
  }

  if (startContainer === editor) {
    const previousChild = editor.childNodes[startOffset - 1];
    if (previousChild?.nodeType === Node.TEXT_NODE) {
      return previousChild.textContent?.slice(-1) || '';
    }
  }

  return '';
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
  const insertionTargetId = useId();
  const editorRef = useRef<HTMLDivElement>(null);
  const lastSelectionRangeRef = useRef<Range | null>(null);
  const lastRenderedValueRef = useRef<string | null>(null);
  const lastTokenLabelsRef = useRef('');
  const composingRef = useRef(false);
  const draggedTokenRef = useRef<HTMLElement | null>(null);
  const dragPreviewRef = useRef<HTMLElement | null>(null);
  const [isEmpty, setIsEmpty] = useState(!value);
  const [dropCaret, setDropCaret] = useState<DropCaret | null>(null);
  const portalRoot = typeof document === 'undefined' ? null : document.body;
  const { activeTarget, registerTarget, setActiveTarget, clearMessage } =
    useVariableInsertion();
  const targetLabel = ariaLabel || '텍스트 필드';
  const isActiveInsertionTarget = activeTarget?.id === insertionTargetId;

  const syncPlaceholder = useCallback(() => {
    const editor = editorRef.current;
    if (!editor) return;
    setIsEmpty(isEditorEmpty(editor));
  }, []);

  const emitChange = useCallback(() => {
    const editor = editorRef.current;
    if (!editor) return;

    const nextValue = serializeEditor(editor);
    lastRenderedValueRef.current = nextValue;
    syncPlaceholder();
    onChange(nextValue);
  }, [onChange, syncPlaceholder]);

  const rememberSelectionRange = useCallback(() => {
    const editor = editorRef.current;
    if (!editor) return;

    const range = getActiveRange(editor);
    if (range) lastSelectionRangeRef.current = range.cloneRange();
  }, []);

  const activateInsertionTarget = useCallback(() => {
    setActiveTarget({
      id: insertionTargetId,
      kind: 'text',
      label: targetLabel,
    });
    clearMessage();
    rememberSelectionRange();
  }, [
    clearMessage,
    insertionTargetId,
    rememberSelectionRange,
    setActiveTarget,
    targetLabel,
  ]);

  const getRememberedRange = useCallback(() => {
    const editor = editorRef.current;
    const range = lastSelectionRangeRef.current;
    if (!editor || !range) return null;

    try {
      if (!editor.contains(range.commonAncestorContainer)) return null;
      return range.cloneRange();
    } catch {
      return null;
    }
  }, []);

  const insertOutputToken = useCallback(
    (output: DraggedOutputVariable, range?: Range | null) => {
      const editor = editorRef.current;
      if (!editor) return false;

      const droppedName = onDropOutput?.(output) || output.key;
      const label = tokenLabels[droppedName] || output.label || droppedName;
      const tokenNode = createTokenNode(droppedName, label);

      insertNodeAtRange(editor, tokenNode, range ?? getRememberedRange());
      emitChange();
      rememberSelectionRange();
      return true;
    },
    [
      emitChange,
      getRememberedRange,
      onDropOutput,
      rememberSelectionRange,
      tokenLabels,
    ],
  );

  useEffect(
    () =>
      registerTarget(
        {
          id: insertionTargetId,
          kind: 'text',
          label: targetLabel,
        },
        (output) => insertOutputToken(output),
      ),
    [insertOutputToken, insertionTargetId, registerTarget, targetLabel],
  );

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
  }, [syncPlaceholder, value, tokenLabels]);

  useEffect(() => {
    syncPlaceholder();

    return () => {
      dragPreviewRef.current?.remove();
      dragPreviewRef.current = null;
    };
  }, [syncPlaceholder]);

  const handleDragOver = (event: DragEvent<HTMLDivElement>) => {
    const isOutputDrop = event.dataTransfer.types.includes(
      NODE_OUTPUT_DRAG_MIME,
    );
    const isTokenMove = event.dataTransfer.types.includes(
      TOKEN_INTERNAL_DRAG_MIME,
    );
    if (!isOutputDrop && !isTokenMove) return;

    event.preventDefault();
    event.stopPropagation();
    event.dataTransfer.dropEffect = isTokenMove ? 'move' : 'copy';

    const editor = editorRef.current;
    if (!editor) return;

    const dropRange = getPointRange(editor, event.clientX, event.clientY);
    setDropCaret(getRangeCaret(editor, dropRange));
  };

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    const isTokenMove = event.dataTransfer.types.includes(
      TOKEN_INTERNAL_DRAG_MIME,
    );
    const output = parseDraggedOutput(event.dataTransfer);
    const editor = editorRef.current;
    if (!editor || (!output && !isTokenMove)) return;

    event.preventDefault();
    event.stopPropagation();
    setDropCaret(null);

    editor.focus();

    const dropRange = getPointRange(editor, event.clientX, event.clientY);
    if (dropRange) selectRange(dropRange);

    if (isTokenMove) {
      const draggedToken = draggedTokenRef.current;
      if (!draggedToken || !editor.contains(draggedToken)) return;
      if (isNoopTokenMove(editor, draggedToken, dropRange)) return;

      insertNodeAtRange(editor, draggedToken, dropRange);
      emitChange();
      return;
    }

    if (!output) return;

    insertOutputToken(output, dropRange);
  };

  const handleDragStart = (event: DragEvent<HTMLDivElement>) => {
    const editor = editorRef.current;
    if (!editor) return;

    const target = event.target as HTMLElement;
    const token = target.closest(`[${TOKEN_ATTR}="true"]`);
    if (!token || !editor.contains(token)) return;

    const tokenElement = token as HTMLElement;
    const name = tokenElement.getAttribute(TOKEN_NAME_ATTR) || '';
    const label = tokenElement.textContent || name;
    draggedTokenRef.current = tokenElement;
    tokenElement.classList.add('opacity-50');

    event.stopPropagation();
    event.dataTransfer.effectAllowed = 'move';
    event.dataTransfer.setData(TOKEN_INTERNAL_DRAG_MIME, name);
    event.dataTransfer.setData('text/plain', label);

    const preview = createTokenDragPreview(label);
    dragPreviewRef.current = preview;

    const tokenRect = tokenElement.getBoundingClientRect();
    const previewRect = preview.getBoundingClientRect();
    const offsetX = Math.min(
      Math.max(event.clientX - tokenRect.left, 0),
      previewRect.width,
    );
    const offsetY = Math.min(
      Math.max(event.clientY - tokenRect.top, 0),
      previewRect.height,
    );
    event.dataTransfer.setDragImage(preview, offsetX, offsetY);
  };

  const handleDragEnd = () => {
    draggedTokenRef.current?.classList.remove('opacity-50');
    draggedTokenRef.current = null;
    dragPreviewRef.current?.remove();
    dragPreviewRef.current = null;
    setDropCaret(null);
  };

  const handleDragLeave = (event: DragEvent<HTMLDivElement>) => {
    const nextTarget = event.relatedTarget as Node | null;
    if (nextTarget && event.currentTarget.contains(nextTarget)) return;
    setDropCaret(null);
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

  const handleBeforeInput = (event: React.FormEvent<HTMLDivElement>) => {
    const nativeEvent = event.nativeEvent as InputEvent;
    if (nativeEvent.data !== '{') return;

    const editor = editorRef.current;
    if (!editor) return;

    const range = getActiveRange(editor);
    if (!range) return;

    if (getCharacterBeforeRange(editor, range) === '{') {
      event.preventDefault();
    }
  };

  const handlePaste = (event: React.ClipboardEvent<HTMLDivElement>) => {
    const editor = editorRef.current;
    if (!editor) return;

    event.preventDefault();
    const text = event.clipboardData
      .getData('text/plain')
      .replaceAll('{{', '{ {')
      .replaceAll('}}', '} }');
    insertNodeAtSelection(editor, createTextNode(text));
    emitChange();
  };

  return (
    <div
      className={cn(
        'relative rounded border border-gray-300 bg-white text-sm text-gray-800 focus-within:border-blue-500 focus-within:outline-none',
        isActiveInsertionTarget && 'ring-2 ring-blue-100',
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
      {dropCaret &&
        portalRoot &&
        createPortal(
          <div
            className="pointer-events-none fixed z-[9999] w-0.5 rounded-full bg-blue-600 shadow-[0_0_0_2px_rgba(37,99,235,0.14)]"
            style={{
              left: dropCaret.left,
              top: dropCaret.top,
              height: dropCaret.height,
            }}
          />,
          portalRoot,
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
        onBeforeInput={handleBeforeInput}
        onInput={handleInput}
        onClick={activateInsertionTarget}
        onDragEnd={handleDragEnd}
        onDragLeave={handleDragLeave}
        onDragStart={handleDragStart}
        onFocus={activateInsertionTarget}
        onKeyDown={handleKeyDown}
        onKeyUp={rememberSelectionRange}
        onMouseUp={rememberSelectionRange}
        onPaste={handlePaste}
      />
    </div>
  );
};
