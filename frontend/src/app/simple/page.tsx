"use client";

import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { ArrowLeft, BarChart3, IndianRupee, Mic, MicOff, PackagePlus, ShoppingBag } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { ReadResult } from "@/components/command-bar";
import { ThemeToggle } from "@/components/theme-toggle";
import { Spinner, Sprite } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { type Candidate, type Interpretation, useAssistant } from "@/lib/assistant";
import { useAuth } from "@/lib/auth";
import { setUiMode } from "@/lib/ui-mode";
import { formatINR } from "@/lib/money";
import type { DashboardSummary } from "@/lib/types";

// Simple mode: one question per screen, big targets, the assistant fills in the details and nothing
// changes until the person taps "Yes, do it".

interface Task {
  id: string;
  label: string;
  question: string;
  example: string;
  icon: React.ComponentType<{ className?: string }>;
  fill: string;
  // Turns what the person said into a phrase the assistant understands.
  toCommand: (said: string) => string;
}

const TASKS: Task[] = [
  {
    id: "sell",
    label: "Sell",
    question: "Who bought what?",
    example: "2 soap 1 atta for Ramesh",
    icon: ShoppingBag,
    fill: "bg-butter",
    toCommand: (s) => (/^\s*(bill|sell|sold)\b/i.test(s) ? s : `bill ${s}`),
  },
  {
    id: "money",
    label: "Money received",
    question: "Who paid, and how much?",
    example: "Ramesh 500 cash",
    icon: IndianRupee,
    fill: "bg-mint",
    toCommand: (s) => (/\b(paid|diye|diya|payment)\b/i.test(s) ? s : s.replace(/(\d)/, "paid $1")),
  },
  {
    id: "stock",
    label: "Stock came in",
    question: "What arrived?",
    example: "20 atta 10 sugar",
    icon: PackagePlus,
    fill: "bg-sky",
    toCommand: (s) => (/^\s*(received|got|aaya)\b/i.test(s) ? s : `received ${s}`),
  },
];

export default function SimplePage() {
  const { me, loading, authenticated, can, logout } = useAuth();
  const router = useRouter();
  const a = useAssistant();
  const [task, setTask] = useState<Task | null>(null);
  const [business, setBusiness] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  // Tapping a tile opens its question with the keyboard already up.
  useEffect(() => {
    if (task) inputRef.current?.focus();
  }, [task]);

  useEffect(() => {
    if (!loading && !authenticated) router.replace("/login");
  }, [loading, authenticated, router]);

  const summary = useQuery({
    queryKey: ["dashboard", "summary"],
    queryFn: () => api.get<DashboardSummary>("/dashboard/summary"),
    enabled: authenticated && can("dashboard.view"),
  });

  if (loading || !me) return <Spinner label="Opening your shop" />;

  const home = () => {
    a.stopListening();
    a.reset();
    setTask(null);
    setBusiness(false);
  };
  const toCommand = task?.toCommand ?? ((s: string) => s);
  const submit = () => a.interpret(toCommand(a.text));
  const showingResult = Boolean(a.busy || a.out || a.error || business);

  return (
    <div className="mx-auto flex min-h-screen w-full max-w-xl flex-col px-4 pb-10 text-lg">
      <header className="flex items-center gap-3 py-4">
        <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-sm border-2 border-line-strong bg-butter shadow-sm">
          <Sprite name="crate" size={24} />
        </div>
        <div className="min-w-0 flex-1">
          <p className="truncate text-base font-semibold leading-5">{me.shop.name}</p>
          <p className="truncate text-sm text-ink-3">Hello, {me.user.full_name.split(" ")[0]}</p>
        </div>
        <ThemeToggle />
      </header>

      {(task || showingResult) && (
        <button onClick={home} className="mb-4 flex min-h-12 items-center gap-2 self-start font-mono text-base font-semibold">
          <ArrowLeft className="h-5 w-5" aria-hidden /> Back
        </button>
      )}

      {showingResult ? (
        business && summary.data ? (
          <Business s={summary.data} onHome={home} />
        ) : (
          <Result a={a} onHome={home} />
        )
      ) : (
        <>
          {!task && summary.data && <Today s={summary.data} />}

          <form
            onSubmit={(e) => {
              e.preventDefault();
              submit();
            }}
            className="mb-6"
          >
            <label htmlFor="say" className="mb-2 block text-2xl font-semibold leading-8">
              {task ? task.question : "What happened?"}
            </label>
            <div className="flex gap-3">
              <input
                id="say"
                ref={inputRef}
                value={a.text}
                onChange={(e) => a.setText(e.target.value)}
                placeholder={task ? task.example : "Type or tap the mic"}
                autoComplete="off"
                className="h-16 min-w-0 flex-1 rounded-sm border-[3px] border-line-strong bg-surface px-4 text-lg placeholder:text-ink-3 focus:shadow-md"
              />
              {a.speechSupported && (
                <button
                  type="button"
                  onClick={() => a.listen(toCommand)}
                  aria-label={a.listening ? "Stop listening" : "Speak"}
                  className={clsx(
                    "px-press flex h-16 w-16 shrink-0 items-center justify-center rounded-sm border-[3px] border-line-strong text-on-pastel",
                    a.listening ? "animate-pulse bg-pink" : "bg-lavender",
                  )}
                >
                  {a.listening ? <MicOff className="h-7 w-7" /> : <Mic className="h-7 w-7" />}
                </button>
              )}
            </div>
            {a.listening && <p className="mt-2 text-base font-semibold">Listening… speak now</p>}
            {a.text.trim() && (
              <BigButton type="submit" className="mt-3 w-full bg-butter">
                Go
              </BigButton>
            )}
            {task && !a.text.trim() && <p className="mt-2 text-base text-ink-2">For example: “{task.example}”</p>}
          </form>

          {!task && (
            <div className="grid grid-cols-2 gap-4">
              {TASKS.map((t) => (
                <Tile key={t.id} icon={t.icon} label={t.label} fill={t.fill} onClick={() => setTask(t)} />
              ))}
              <Tile icon={BarChart3} label="How's business today?" fill="bg-lavender" onClick={() => (summary.data ? setBusiness(true) : a.interpret("today's sales"))} />
            </div>
          )}

          <div className="mt-auto flex items-center justify-between gap-4 pt-10 text-base">
            <Link
              href="/"
              onClick={() => setUiMode("full")}
              className="font-mono font-semibold text-info underline underline-offset-4"
            >
              Switch to full view
            </Link>
            <button onClick={logout} className="font-mono text-ink-2 underline underline-offset-4">
              Sign out
            </button>
          </div>
        </>
      )}
    </div>
  );
}

function Today({ s }: { s: DashboardSummary }) {
  return (
    <section aria-label="Today" className="mb-6 border-[3px] border-line-strong bg-surface p-4 shadow-md">
      <p className="text-base text-ink-2">Sold today</p>
      <p className="mt-1 font-pixel text-xl leading-9">{formatINR(s.today.revenue)}</p>
      <p className="text-base text-ink-2">
        {s.today.invoice_count} {s.today.invoice_count === 1 ? "bill" : "bills"}
      </p>
      {s.stock.low_stock + s.stock.out_of_stock > 0 && (
        <p className="mt-3 flex items-center gap-2 border-t-2 border-line pt-3 text-base font-semibold text-critical-ink">
          <Sprite name="alert" size={24} />
          {s.stock.low_stock + s.stock.out_of_stock} items running low
        </p>
      )}
    </section>
  );
}

function Business({ s, onHome }: { s: DashboardSummary; onHome: () => void }) {
  const low = s.stock.low_stock + s.stock.out_of_stock;
  const lines = [
    `You sold ${formatINR(s.today.revenue)} today in ${s.today.invoice_count} ${s.today.invoice_count === 1 ? "bill" : "bills"}.`,
    low ? `${low} ${low === 1 ? "item is" : "items are"} running low. Order soon.` : "All shelves are stocked.",
    s.khata.customers_with_balance
      ? `${s.khata.customers_with_balance} customers owe you ${formatINR(s.khata.outstanding)} on khata.`
      : "Nobody owes you money right now.",
  ];
  return (
    <Panel className="bg-surface">
      <p className="text-2xl font-semibold">Today at a glance</p>
      <ul className="mt-4 flex flex-col gap-4 text-xl leading-7">
        {lines.map((l) => (
          <li key={l}>{l}</li>
        ))}
      </ul>
      <BigButton onClick={onHome} className="mt-6 w-full bg-butter">
        OK
      </BigButton>
    </Panel>
  );
}

function Tile({
  icon: Icon,
  label,
  fill,
  onClick,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  fill: string;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={clsx(
        "px-press flex min-h-32 flex-col items-start justify-between gap-3 rounded-sm border-[3px] border-line-strong p-4 text-left text-on-pastel",
        fill,
      )}
    >
      <Icon className="h-8 w-8" aria-hidden />
      <span className="text-xl font-semibold leading-6">{label}</span>
    </button>
  );
}

function BigButton({ className, ...rest }: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      className={clsx(
        "px-press flex min-h-16 items-center justify-center gap-2 rounded-sm border-[3px] border-line-strong px-6 font-mono text-xl font-semibold text-on-pastel disabled:opacity-60",
        className,
      )}
      {...rest}
    />
  );
}

function Result({ a, onHome }: { a: ReturnType<typeof useAssistant>; onHome: () => void }) {
  if (a.busy && !a.out) return <Spinner label="Working it out" />;

  if (a.error && !a.out)
    return (
      <Panel className="bg-pink-soft">
        <p className="text-xl font-semibold">That didn’t go through.</p>
        <p className="mt-2 text-lg">{a.error instanceof ApiError ? a.error.message : "Please check your internet and try again."}</p>
        <BigButton onClick={onHome} className="mt-5 w-full bg-surface !text-ink">
          Start again
        </BigButton>
      </Panel>
    );

  const out = a.out!;

  if (a.done)
    return (
      <Panel className="bg-mint-soft">
        <p className="flex items-center gap-3 text-2xl font-semibold">
          <Sprite name="check" size={36} /> Done
        </p>
        <ul className="mt-3 flex flex-col gap-2 text-lg">
          {a.done.map((d, i) => (
            <li key={i}>
              {d.label}
              {d.href && (
                <Link href={d.href} className="ml-2 font-semibold text-info underline underline-offset-4">
                  See bill
                </Link>
              )}
            </li>
          ))}
        </ul>
        <BigButton onClick={onHome} className="mt-5 w-full bg-butter">
          Next
        </BigButton>
      </Panel>
    );

  if (out.kind === "read")
    return (
      <Panel className="bg-surface">
        <p className="text-xl font-semibold leading-8">{out.message}</p>
        <div className="mt-3 text-base">
          <ReadResult result={out.result} />
        </div>
        <BigButton onClick={onHome} className="mt-5 w-full bg-butter">
          OK
        </BigButton>
      </Panel>
    );

  const p = out.proposal;
  if (!p || out.intent === "unknown")
    return (
      <Panel className="bg-surface">
        <p className="text-xl font-semibold">Sorry, I didn’t understand that.</p>
        <p className="mt-2 text-lg text-ink-2">Try saying it like: “2 soap for Ramesh” or “Ramesh paid 500”.</p>
        <BigButton onClick={onHome} className="mt-5 w-full bg-butter">
          Try again
        </BigButton>
      </Panel>
    );

  const choices = Object.entries(out.candidates);
  const isSale = out.intent === "invoice_draft";
  return (
    <Panel className="bg-butter-soft">
      <p className="text-base font-semibold uppercase tracking-wide text-ink-2">Please check</p>
      <p className="mt-1 text-2xl font-semibold leading-8">{TITLES[out.intent] ?? p.title}</p>
      <ul className="mt-3 flex flex-col gap-2 text-lg">
        {p.summary.filter((line) => !line.startsWith("Estimated total")).map((line, i) => (
          <li key={i} className="tabular">
            {line}
          </li>
        ))}
      </ul>
      {p.preview?.grand_total && (
        <p className="mt-4 border-t-2 border-line-strong pt-3 text-2xl font-semibold">Total {formatINR(p.preview.grand_total)}</p>
      )}

      {choices.map(([key, list]) => (
        <div key={key} className="mt-5">
          <p className="text-lg font-semibold">Which one did you mean?</p>
          <div className="mt-2 flex flex-col gap-2">
            {list.map((c) => (
              <button
                key={c.id}
                onClick={() => a.interpret(withChoice(out, key, c))}
                className="px-press min-h-14 rounded-sm border-[3px] border-line-strong bg-surface px-4 py-2 text-left text-lg"
              >
                <span className="font-semibold">{c.label}</span>
                {c.detail && <span className="block text-base text-ink-2">{c.detail}</span>}
              </button>
            ))}
          </div>
        </div>
      ))}

      {!choices.length && p.warnings.length > 0 && (
        <ul className="mt-4 flex flex-col gap-2">
          {p.warnings.map((w, i) => (
            <li key={i} className="flex items-start gap-2 text-lg font-semibold text-critical-ink">
              <Sprite name="alert" size={24} className="mt-0.5" /> {w}
            </li>
          ))}
        </ul>
      )}

      {a.error ? (
        <p role="alert" className="mt-5 border-2 border-line-strong bg-pink-soft p-3 text-lg font-semibold text-critical-ink">
          {a.error instanceof ApiError ? a.error.message : "That didn’t go through. Please try again."}
        </p>
      ) : null}

      {!p.permitted ? (
        <p className="mt-5 text-lg font-semibold">You don’t have permission for this. Please ask the shop owner.</p>
      ) : (
        <div className="mt-6 flex flex-col gap-3">
          {p.ready && isSale && (
            <>
              <p className="text-xl font-semibold">{a.busy ? "Saving…" : "How did they pay?"}</p>
              <BigButton onClick={() => a.confirm({ method: "cash" })} disabled={a.busy} className="w-full bg-butter">
                Paid cash
              </BigButton>
              <BigButton onClick={() => a.confirm({ method: "upi" })} disabled={a.busy} className="w-full bg-butter">
                Paid by UPI
              </BigButton>
              {out.entities.customer_query && (
                <BigButton onClick={() => a.confirm("khata")} disabled={a.busy} className="w-full bg-lavender">
                  On khata (pay later)
                </BigButton>
              )}
            </>
          )}
          {p.ready && !isSale && (
            <BigButton onClick={() => a.confirm()} disabled={a.busy} className="w-full bg-butter">
              {a.busy ? "Saving…" : "Yes, do it"}
            </BigButton>
          )}
          <BigButton onClick={onHome} className="w-full bg-surface !text-ink">
            {p.ready ? "No, cancel" : "Start again"}
          </BigButton>
        </div>
      )}
    </Panel>
  );
}

const TITLES: Record<string, string> = {
  invoice_draft: "New sale",
  payment_record: "Money received",
  stock_receipt: "Stock came in",
  stock_adjustment: "Fix stock count",
};

function Panel({ className, children }: { className: string; children: React.ReactNode }) {
  return <section className={clsx("border-[3px] border-line-strong p-5 shadow-md", className)}>{children}</section>;
}

// Re-asks with the ambiguous word replaced by the picked product's SKU or customer's full name.
function withChoice(out: Interpretation, key: string, c: Candidate): string {
  const e = out.entities;
  const query =
    key === "customer" ? e.customer_query : key === "product" ? e.product_query : e.items[Number(key.split("_")[1])]?.query;
  const value = key === "customer" ? c.label : (c.label.match(/\(([^)]+)\)$/)?.[1] ?? c.label);
  if (!query) return `${out.text} ${value}`;
  const re = new RegExp(query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "i");
  return re.test(out.text) ? out.text.replace(re, value) : `${out.text} ${value}`;
}
