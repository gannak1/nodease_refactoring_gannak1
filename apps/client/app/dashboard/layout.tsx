import Sidebar from '../features/dashboard/components/Sidebar';

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex h-screen overflow-hidden bg-slate-50 font-sans text-slate-950">
      <Sidebar />

      <div className="relative z-0 flex flex-1 flex-col overflow-hidden bg-slate-50">
        <main className="flex-1 overflow-y-auto">{children}</main>
      </div>
    </div>
  );
}
