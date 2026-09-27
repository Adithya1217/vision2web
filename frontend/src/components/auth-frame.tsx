export function AuthFrame({ title, subtitle, children }: { title: string; subtitle: string; children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center px-4 py-10">
      <div className="w-full max-w-md">
        <div className="mb-6 flex items-center gap-2">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-accent font-bold text-accent-ink">D</div>
          <span className="text-lg font-semibold">Dukaan Desk</span>
        </div>
        <div className="rounded-2xl border border-line bg-surface p-6">
          <h1 className="text-xl font-semibold">{title}</h1>
          <p className="mb-5 text-sm text-ink-2">{subtitle}</p>
          {children}
        </div>
      </div>
    </div>
  );
}
