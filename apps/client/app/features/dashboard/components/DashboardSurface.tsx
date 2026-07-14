import type { ReactNode } from 'react';
import type { LucideIcon } from 'lucide-react';

type DashboardPageHeaderProps = {
  icon: LucideIcon;
  title: string;
  description: string;
  meta?: ReactNode;
  badge?: ReactNode;
  action?: ReactNode;
};

export function DashboardPageHeader({
  icon: Icon,
  title,
  description,
  meta,
  badge,
  action,
}: DashboardPageHeaderProps) {
  return (
    <header className="border-b border-slate-200 pb-5">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex min-w-0 items-center gap-4">
          <div className="grid h-11 w-11 shrink-0 place-items-center rounded-lg bg-slate-950 text-white">
            <Icon className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-xl font-bold text-slate-950">{title}</h1>
              {badge}
            </div>
            <p className="mt-1 text-sm font-medium text-slate-700">
              {description}
            </p>
            {meta && <div className="mt-2">{meta}</div>}
          </div>
        </div>
        {action}
      </div>
    </header>
  );
}

type DashboardSummaryCardProps = {
  label: string;
  value: string | number;
  icon: LucideIcon;
  iconClassName?: string;
  valueClassName?: string;
  descriptionClassName?: string;
  description?: string;
};

export function DashboardSummaryCard({
  label,
  value,
  icon: Icon,
  iconClassName = 'text-blue-600',
  valueClassName = 'mt-1 text-lg',
  descriptionClassName = 'mt-1 text-xs',
  description,
}: DashboardSummaryCardProps) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-medium text-slate-500">{label}</p>
          <p
            className={`truncate font-semibold text-slate-950 ${valueClassName}`}
          >
            {value}
          </p>
          {description && (
            <p className={`text-slate-500 ${descriptionClassName}`}>
              {description}
            </p>
          )}
        </div>
        <Icon className={`h-5 w-5 shrink-0 ${iconClassName}`} />
      </div>
    </div>
  );
}

type DashboardPanelProps = {
  title: string;
  icon?: LucideIcon;
  aside?: ReactNode;
  children: ReactNode;
};

export function DashboardPanel({
  title,
  icon: Icon,
  aside,
  children,
}: DashboardPanelProps) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 px-5 py-3">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-950">
          {Icon && <Icon className="h-4 w-4 text-blue-600" />}
          {title}
        </h2>
        {aside}
      </div>
      {children}
    </section>
  );
}
