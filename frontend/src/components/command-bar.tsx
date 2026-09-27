"use client";

import { AlertTriangle, CheckCircle2, Mic, MicOff, Send, ShieldCheck, Sparkles } from "lucide-react";
import Link from "next/link";

import { useToast } from "@/components/toast";
import { Badge, Button, ErrorBanner, Input, Modal } from "@/components/ui";
import { useAssistant } from "@/lib/assistant";
import { formatINR } from "@/lib/money";

const EXAMPLES = [
  "stock of parle-g",
  "received 24 colgate",
  "bill 2 RICE-5KG and 1 SUGAR-1KG for Ramesh",
  "Ramesh paid 500 upi",
  "khata of Sunita",
  "sales this week",
  "top products by units this month",
];

export function CommandBar({ open, onClose }: { open: boolean; onClose: () => void }) {
  const toast = useToast();
  const { text, setText, busy, error, out, done, listening, speechSupported, interpret, listen, stopListening, confirm, reset } =
    useAssistant({ onDone: (title) => toast(title + " — done") });

  const close = () => {
    stopListening();
    onClose();
  };

  return (
    <Modal open={open} onClose={close} title="Assistant" wide>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          interpret();
        }}
        className="flex gap-2"
      >
        <Input
          autoFocus
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Type or speak: “bill 2 soap for Ramesh”"
          aria-label="Command"
        />
        {speechSupported && (
          <Button type="button" onClick={() => listen()} aria-label={listening ? "Stop listening" : "Speak a command"} variant={listening ? "danger" : "secondary"}>
            {listening ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
          </Button>
        )}
        <Button type="submit" variant="primary" loading={busy && !out} aria-label="Run">
          <Send className="h-4 w-4" />
        </Button>
      </form>

      {!out && !error && (
        <div className="mt-4">
          <p className="mb-2 text-xs font-medium text-ink-3">Try</p>
          <div className="flex flex-wrap gap-1.5">
            {EXAMPLES.map((ex) => (
              <button
                key={ex}
                onClick={() => {
                  setText(ex);
                  interpret(ex);
                }}
                className="rounded-md border-2 border-line-strong bg-surface px-2.5 py-1 font-mono text-xs text-ink-2 hover:bg-lavender-soft hover:text-ink"
              >
                {ex}
              </button>
            ))}
          </div>
          <p className="mt-4 flex items-start gap-1.5 text-xs text-ink-3">
            <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
            Questions are answered right away. Anything that changes data is shown for your confirmation first and
            then runs through the normal, permission-checked API.
          </p>
        </div>
      )}

      <ErrorBanner error={error} className="mt-3" />

      {out && (
        <div className="mt-4 flex flex-col gap-3">
          <div className="flex items-start gap-2">
            <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-info" aria-hidden />
            <div className="flex-1">
              <p className="text-sm">{out.message}</p>
              <p className="mt-0.5 text-xs text-ink-3">
                {out.intent.replace("_", " ")} · {out.source === "llm" ? "AI parser" : "rule parser"}
              </p>
            </div>
          </div>

          {out.kind === "read" && <ReadResult result={out.result} />}

          {out.proposal && (
            <div className="border-2 border-line-strong bg-butter-soft p-3">
              <div className="mb-2 flex items-center justify-between gap-2">
                <h3 className="font-pixel text-[10px] leading-4">{out.proposal.title}</h3>
                {out.proposal.ready ? <Badge tone="info">Needs confirmation</Badge> : <Badge tone="warning">Incomplete</Badge>}
              </div>
              <ul className="flex flex-col gap-1 text-sm">
                {out.proposal.summary.map((line, i) => (
                  <li key={i} className="tabular">
                    {line}
                  </li>
                ))}
              </ul>
              {out.proposal.preview?.note && <p className="mt-2 text-xs text-ink-3">{out.proposal.preview.note}</p>}
              {out.proposal.warnings.length > 0 && (
                <ul className="mt-2 flex flex-col gap-1">
                  {out.proposal.warnings.map((w, i) => (
                    <li key={i} className="flex items-start gap-1.5 text-xs text-warning-ink">
                      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
                      {w}
                    </li>
                  ))}
                </ul>
              )}
              {Object.entries(out.candidates).map(([k, list]) => (
                <div key={k} className="mt-2">
                  <p className="text-xs text-ink-3">Did you mean:</p>
                  <div className="mt-1 flex flex-wrap gap-1.5">
                    {list.map((c) => (
                      <span key={c.id} className="rounded-md border-2 border-line-strong bg-surface px-2 py-0.5 font-mono text-xs">
                        {c.label}
                        {c.detail && <span className="text-ink-3"> · {c.detail}</span>}
                      </span>
                    ))}
                  </div>
                </div>
              ))}
              {done ? (
                <div className="mt-3 flex flex-col gap-1">
                  {done.map((d, i) => (
                    <p key={i} className="flex items-center gap-1.5 text-sm text-good-ink">
                      <CheckCircle2 className="h-4 w-4" aria-hidden /> {d.label}
                      {d.href && (
                        <Link href={d.href} onClick={close} className="ml-1 text-info underline">
                          Open
                        </Link>
                      )}
                    </p>
                  ))}
                  <Button size="sm" className="mt-2 self-start" onClick={reset}>
                    New command
                  </Button>
                </div>
              ) : (
                <div className="mt-3 flex gap-2">
                  <Button variant="primary" onClick={() => confirm()} loading={busy} disabled={!out.proposal.ready}>
                    Confirm
                  </Button>
                  <Button variant="ghost" onClick={reset}>
                    Cancel
                  </Button>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </Modal>
  );
}

export function ReadResult({ result }: { result: unknown }) {
  if (!result) return null;
  if (Array.isArray(result)) {
    if (!result.length) return null;
    const rows = result.slice(0, 8) as Record<string, unknown>[];
    const cols = ["name", "product_name", "sku", "quantity", "sale_price", "balance", "overdue"].filter((c) => c in rows[0]);
    return (
      <div className="overflow-x-auto border-2 border-line-strong">
        <table className="w-full text-sm">
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className="border-b border-line last:border-0">
                {cols.map((c) => (
                  <td key={c} className="tabular px-3 py-1.5">
                    {["sale_price", "balance", "overdue"].includes(c) ? formatINR(String(r[c])) : String(r[c] ?? "—")}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  const obj = result as Record<string, unknown>;
  if (obj.rows && Array.isArray(obj.rows)) return <ReadResult result={obj.rows} />;
  return null;
}
