import { Sprite } from "@/components/ui";

export function AuthFrame({ title, subtitle, children }: { title: string; subtitle: string; children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center px-4 py-10">
      <div className="w-full max-w-md">
        <div className="mb-6 flex items-center gap-2">
          <div className="flex h-10 w-10 items-center justify-center rounded-sm border-2 border-line-strong bg-butter shadow-sm">
            <Sprite name="crate" size={24} />
          </div>
          <span className="font-pixel text-sm">DUKAAN DESK</span>
        </div>
        <div className="border-[3px] border-line-strong bg-surface p-6 shadow-lg">
          <h1 className="mb-1 font-pixel text-base leading-7">{title}</h1>
          <p className="mb-5 text-sm text-ink-2">{subtitle}</p>
          {children}
        </div>
      </div>
    </div>
  );
}
