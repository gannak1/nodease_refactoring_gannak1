'use client';

type PreviewValue = string | number | boolean | null | PreviewValue[] | {
  [key: string]: PreviewValue;
};

interface CostOptimizerPreviewViewerProps {
  value: unknown;
  emptyText?: string;
  className?: string;
}

const parseJsonLikeString = (value: string): unknown => {
  const trimmed = value.trim();
  if (!trimmed || (!trimmed.startsWith('{') && !trimmed.startsWith('['))) {
    return value;
  }

  try {
    return JSON.parse(trimmed);
  } catch {
    return value;
  }
};

const normalizeCostOptimizerPreview = (
  value: unknown,
  depth = 0,
): PreviewValue => {
  if (depth > 8) return String(value);
  if (value === null || value === undefined) return null;
  if (
    typeof value === 'number' ||
    typeof value === 'boolean'
  ) {
    return value;
  }
  if (typeof value === 'string') {
    const parsed = parseJsonLikeString(value);
    if (parsed !== value) {
      return normalizeCostOptimizerPreview(parsed, depth + 1);
    }
    return value;
  }
  if (Array.isArray(value)) {
    return value.map((item) => normalizeCostOptimizerPreview(item, depth + 1));
  }
  if (typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([key, item]) => [
        key,
        normalizeCostOptimizerPreview(item, depth + 1),
      ]),
    );
  }

  return String(value);
};

const valueToCopyText = (value: PreviewValue): string => {
  if (value === null) return 'null';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }
  return JSON.stringify(value, null, 2);
};

const PreviewLeaf = ({ value }: { value: string | number | boolean | null }) => {
  if (value === null) {
    return <span className="text-slate-400">null</span>;
  }
  if (typeof value === 'boolean') {
    return (
      <span
        className={
          value ? 'font-semibold text-emerald-700' : 'font-semibold text-red-600'
        }
      >
        {String(value)}
      </span>
    );
  }
  if (typeof value === 'number') {
    return <span className="font-mono text-blue-700">{value}</span>;
  }

  return (
    <span className="whitespace-pre-wrap break-words text-slate-800">
      {value}
    </span>
  );
};

const PreviewNode = ({
  value,
  level = 0,
}: {
  value: PreviewValue;
  level?: number;
}) => {
  if (
    value === null ||
    typeof value === 'string' ||
    typeof value === 'number' ||
    typeof value === 'boolean'
  ) {
    return <PreviewLeaf value={value} />;
  }

  if (Array.isArray(value)) {
    if (value.length === 0) {
      return <span className="text-slate-400">[]</span>;
    }
    return (
      <span className="grid gap-2">
        {value.map((item, index) => (
          <span
            key={`${level}-${index}`}
            className="grid gap-1 rounded-md border border-slate-100 bg-white/70 px-2 py-1.5"
          >
            <span className="text-[10px] font-bold uppercase tracking-wide text-slate-400">
              {index}
            </span>
            <PreviewNode value={item} level={level + 1} />
          </span>
        ))}
      </span>
    );
  }

  const entries = Object.entries(value);
  if (entries.length === 0) {
    return <span className="text-slate-400">{'{}'}</span>;
  }

  return (
    <span className="grid gap-2">
      {entries.map(([key, item]) => (
        <span
          key={`${level}-${key}`}
          className="grid gap-1 rounded-md border border-slate-100 bg-white/70 px-2 py-1.5"
        >
          <span className="text-[10px] font-bold uppercase tracking-wide text-slate-400">
            {key}
          </span>
          <PreviewNode value={item} level={level + 1} />
        </span>
      ))}
    </span>
  );
};

export function CostOptimizerPreviewViewer({
  value,
  emptyText = '-',
  className = '',
}: CostOptimizerPreviewViewerProps) {
  const normalized = normalizeCostOptimizerPreview(value);
  const isEmpty =
    normalized === null ||
    (typeof normalized === 'string' && normalized.trim().length === 0);

  if (isEmpty) {
    return <span className={className}>{emptyText}</span>;
  }

  return (
    <span
      className={`block whitespace-normal break-words rounded-md bg-slate-50 p-3 text-xs leading-relaxed text-slate-800 ${className}`}
      title={valueToCopyText(normalized)}
    >
      <PreviewNode value={normalized} />
    </span>
  );
}
