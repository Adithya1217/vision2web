"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Printer, ReceiptIndianRupee, Trash2, Undo2 } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";

import { InvoiceStatusBadge, PaymentBadge } from "@/components/badges";
import { useToast } from "@/components/toast";
import { Badge, Button, Card, CardHeader, ErrorBanner, Field, Input, Modal, Select, Spinner, Table, Td, Textarea, Th } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDate, formatDateTime, METHOD_LABEL, stateName } from "@/lib/format";
import { useSubmitter } from "@/lib/hooks";
import { formatINR, fromPaise, isMoney, toPaise } from "@/lib/money";
import type { Invoice, PaymentMethod } from "@/lib/types";

const MONEY_METHODS = ["cash", "upi", "card", "bank_transfer"] as const;

export default function InvoiceDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { me, can } = useAuth();
  const router = useRouter();
  const toast = useToast();
  const qc = useQueryClient();
  const [paying, setPaying] = useState(false);
  const [crediting, setCrediting] = useState(false);
  const inv = useQuery({ queryKey: ["invoice", id], queryFn: () => api.get<Invoice>(`/invoices/${id}`) });

  const post = useMutation({
    mutationFn: () => api.post<Invoice>(`/invoices/${id}/post`, { payments: [] }),
    onSuccess: (i) => {
      qc.invalidateQueries();
      toast(`Posted ${i.number}`);
    },
  });
  const del = useMutation({
    mutationFn: () => api.delete(`/invoices/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["invoices"] });
      toast("Draft deleted");
      router.replace("/invoices");
    },
  });

  if (inv.isLoading) return <Spinner />;
  if (inv.error || !inv.data) return <ErrorBanner error={inv.error ?? "Not found"} />;
  const d = inv.data;
  const shop = me!.shop;
  const intra = d.supply_type === "intra_state";
  const tz = shop.timezone;

  return (
    <>
      <div className="no-print mb-4 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Link href="/invoices" className="text-sm text-ink-3 hover:text-ink">
            Invoices
          </Link>
          <span className="text-ink-3">/</span>
          <h1 className="text-xl font-semibold">{d.number ?? `Draft #${d.id}`}</h1>
          <InvoiceStatusBadge status={d.status} />
          {d.status !== "draft" && <PaymentBadge status={d.payment_status} overdue={d.is_overdue} />}
        </div>
        <div className="flex flex-wrap gap-2">
          {d.status === "draft" ? (
            <>
              <Button variant="ghost" onClick={() => del.mutate()} loading={del.isPending}>
                <Trash2 className="h-4 w-4" /> Delete
              </Button>
              <Link href={`/invoices/new?draft=${d.id}`}>
                <Button>
                  <Pencil className="h-4 w-4" /> Edit / take payment
                </Button>
              </Link>
              {d.customer_id && (
                <Button variant="primary" onClick={() => post.mutate()} loading={post.isPending}>
                  Post on credit
                </Button>
              )}
            </>
          ) : (
            <>
              {can("payments.record") && d.balance_due !== "0.00" && (
                <Button variant="primary" onClick={() => setPaying(true)}>
                  <ReceiptIndianRupee className="h-4 w-4" /> Record payment
                </Button>
              )}
              {can("credit_notes.create") && d.status === "posted" && (
                <Button onClick={() => setCrediting(true)}>
                  <Undo2 className="h-4 w-4" /> Return / credit note
                </Button>
              )}
              <Button variant="ghost" onClick={() => window.print()}>
                <Printer className="h-4 w-4" /> Print
              </Button>
            </>
          )}
        </div>
      </div>
      <ErrorBanner error={post.error ?? del.error} className="no-print mb-3" />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <div className="flex flex-wrap justify-between gap-4 border-b border-line p-5">
            <div>
              <p className="text-lg font-semibold">{shop.legal_name || shop.name}</p>
              {shop.address && <p className="text-sm text-ink-2">{shop.address}</p>}
              {shop.gstin && <p className="text-sm text-ink-2">GSTIN {shop.gstin}</p>}
            </div>
            <div className="text-right text-sm">
              <p className="text-base font-semibold">{d.status === "draft" ? "DRAFT" : "TAX INVOICE"}</p>
              <p className="text-ink-2">{d.number ?? "Not yet numbered"}</p>
              <p className="text-ink-2">Date {formatDate(d.invoice_date ?? d.created_at, tz)}</p>
              {d.due_date && <p className="text-ink-2">Due {formatDate(d.due_date)}</p>}
            </div>
          </div>
          <div className="grid grid-cols-1 gap-2 border-b border-line p-5 text-sm sm:grid-cols-2">
            <div>
              <p className="text-xs uppercase tracking-wide text-ink-3">Bill to</p>
              <p className="font-medium">{d.customer_name ?? "Walk-in customer"}</p>
            </div>
            <div className="sm:text-right">
              <p className="text-xs uppercase tracking-wide text-ink-3">Place of supply</p>
              <p>
                {d.place_of_supply} · {stateName(d.place_of_supply)} ({intra ? "CGST + SGST" : "IGST"})
              </p>
            </div>
          </div>
          <Table>
            <thead>
              <tr>
                <Th>#</Th>
                <Th>Item</Th>
                <Th className="text-right">Qty</Th>
                <Th className="text-right">Rate</Th>
                <Th className="hidden text-right sm:table-cell">Disc.</Th>
                <Th className="hidden text-right md:table-cell">Taxable</Th>
                <Th className="hidden text-right md:table-cell">GST</Th>
                <Th className="text-right">Amount</Th>
              </tr>
            </thead>
            <tbody className="tabular">
              {d.items.map((it) => (
                <tr key={it.id}>
                  <Td className="text-ink-3">{it.line_no}</Td>
                  <Td>
                    <p className="font-medium">{it.product_name}</p>
                    <p className="text-xs text-ink-3">
                      {it.sku}
                      {it.hsn_code && ` · HSN ${it.hsn_code}`}
                      {it.returned_quantity > 0 && ` · ${it.returned_quantity} returned`}
                    </p>
                  </Td>
                  <Td className="text-right">{it.quantity}</Td>
                  <Td className="text-right">{formatINR(it.unit_price)}</Td>
                  <Td className="hidden text-right sm:table-cell">{it.discount_amount === "0.00" ? "—" : formatINR(it.discount_amount)}</Td>
                  <Td className="hidden text-right md:table-cell">{formatINR(it.taxable_value)}</Td>
                  <Td className="hidden text-right md:table-cell">
                    {Number(it.gst_rate)}%
                    <span className="block text-xs text-ink-3">
                      {formatINR(fromPaise(toPaise(it.cgst_amount) + toPaise(it.sgst_amount) + toPaise(it.igst_amount)))}
                    </span>
                  </Td>
                  <Td className="text-right font-medium">{formatINR(it.line_total)}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
          <dl className="tabular ml-auto flex max-w-xs flex-col gap-1 p-5 text-sm">
            <TotalRow label="Subtotal" value={d.subtotal} />
            {d.discount_total !== "0.00" && <TotalRow label="Discount" value={`-${d.discount_total}`} />}
            <TotalRow label="Taxable value" value={d.taxable_total} />
            {intra ? (
              <>
                <TotalRow label="CGST" value={d.cgst_total} />
                <TotalRow label="SGST" value={d.sgst_total} />
              </>
            ) : (
              <TotalRow label="IGST" value={d.igst_total} />
            )}
            <div className="mt-1 flex justify-between border-t border-line pt-2 text-base font-semibold">
              <dt>Grand total</dt>
              <dd>{formatINR(d.grand_total)}</dd>
            </div>
            {d.status !== "draft" && (
              <>
                {d.credited_total !== "0.00" && <TotalRow label="Credited (returns)" value={`-${d.credited_total}`} />}
                <TotalRow label="Paid" value={d.amount_paid} />
                <div className="flex justify-between font-semibold">
                  <dt>Balance due</dt>
                  <dd className={d.balance_due !== "0.00" ? "text-critical-ink" : ""}>{formatINR(d.balance_due)}</dd>
                </div>
              </>
            )}
          </dl>
          {d.notes && <p className="border-t border-line px-5 py-3 text-sm text-ink-2">{d.notes}</p>}
        </Card>

        <div className="no-print flex flex-col gap-4">
          <Card>
            <CardHeader title="Payments" subtitle={d.credit_amount !== "0.00" ? `${formatINR(d.credit_amount)} sold on credit` : undefined} />
            {d.payments.length === 0 ? (
              <p className="px-4 py-4 text-sm text-ink-3">No payments recorded.</p>
            ) : (
              <ul className="divide-y divide-line">
                {d.payments.map((p) => (
                  <li key={p.id} className="flex items-center justify-between px-4 py-2.5 text-sm">
                    <div>
                      <p>
                        {METHOD_LABEL[p.method]} {p.kind === "refund" && <Badge tone="warning">Refund</Badge>}
                      </p>
                      <p className="text-xs text-ink-3">
                        {formatDateTime(p.paid_at, tz)}
                        {p.reference && ` · ${p.reference}`}
                      </p>
                    </div>
                    <span className={`tabular font-medium ${p.kind === "refund" ? "text-critical-ink" : ""}`}>
                      {p.kind === "refund" ? "-" : ""}
                      {formatINR(p.amount)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Card>
          {d.credit_notes.length > 0 && (
            <Card>
              <CardHeader title="Credit notes" />
              <ul className="divide-y divide-line">
                {d.credit_notes.map((n) => (
                  <li key={n.id} className="px-4 py-2.5 text-sm">
                    <div className="flex justify-between">
                      <span className="font-medium">{n.number}</span>
                      <span className="tabular">{formatINR(n.total)}</span>
                    </div>
                    <p className="text-xs text-ink-3">
                      {formatDate(n.note_date)} · {n.reason} · {n.restock ? "restocked" : "not restocked"}
                      {n.refund_amount !== "0.00" && ` · refunded ${formatINR(n.refund_amount)}`}
                    </p>
                  </li>
                ))}
              </ul>
            </Card>
          )}
          {d.customer_id && (
            <Link href={`/customers/${d.customer_id}`} className="text-sm text-accent hover:underline">
              View {d.customer_name}&apos;s khata →
            </Link>
          )}
        </div>
      </div>
      {paying && <PaymentModal invoice={d} onClose={() => setPaying(false)} />}
      {crediting && <CreditNoteModal invoice={d} onClose={() => setCrediting(false)} />}
    </>
  );
}

function TotalRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between text-ink-2">
      <dt>{label}</dt>
      <dd className="text-ink">{formatINR(value)}</dd>
    </div>
  );
}

function PaymentModal({ invoice, onClose }: { invoice: Invoice; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const submitter = useSubmitter();
  const [amount, setAmount] = useState(invoice.balance_due);
  const [method, setMethod] = useState<Exclude<PaymentMethod, "credit">>("cash");
  const [reference, setReference] = useState("");
  const tooMuch = isMoney(amount) && toPaise(amount) > toPaise(invoice.balance_due);
  const save = useMutation({
    mutationFn: () => {
      const body = { method, amount: fromPaise(toPaise(amount)), reference: reference || null };
      return api.post(`/invoices/${invoice.id}/payments`, body, submitter.keyFor(body));
    },
    onSuccess: () => {
      submitter.done();
      qc.invalidateQueries();
      toast("Payment recorded");
      onClose();
    },
  });
  return (
    <Modal
      open
      onClose={onClose}
      title={`Record payment · ${invoice.number}`}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" onClick={() => save.mutate()} loading={save.isPending} disabled={!isMoney(amount) || toPaise(amount) <= 0n || tooMuch}>
            Save payment
          </Button>
        </>
      }
    >
      <ErrorBanner error={save.error} className="mb-3" />
      <p className="mb-3 text-sm text-ink-2">
        Balance due <strong className="tabular">{formatINR(invoice.balance_due)}</strong>
      </p>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="Amount (₹)" error={tooMuch ? "More than the balance due" : undefined}>
          {(id) => <Input id={id} value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="decimal" />}
        </Field>
        <Field label="Method">
          {(id) => (
            <Select id={id} value={method} onChange={(e) => setMethod(e.target.value as typeof method)}>
              {MONEY_METHODS.map((m) => (
                <option key={m} value={m}>
                  {METHOD_LABEL[m]}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="Reference (UTR, cheque no.)" className="sm:col-span-2">
          {(id) => <Input id={id} value={reference} onChange={(e) => setReference(e.target.value)} />}
        </Field>
      </div>
    </Modal>
  );
}

function CreditNoteModal({ invoice, onClose }: { invoice: Invoice; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const submitter = useSubmitter();
  const [qty, setQty] = useState<Record<number, string>>({});
  const [reason, setReason] = useState("");
  const [restock, setRestock] = useState(true);
  const [refund, setRefund] = useState<"" | Exclude<PaymentMethod, "credit">>("");
  const lines = invoice.items
    .map((it) => ({ it, max: it.quantity - it.returned_quantity, n: Number(qty[it.id] || 0) }))
    .filter((l) => l.max > 0);
  const chosen = lines.filter((l) => l.n > 0);
  const invalid = chosen.some((l) => !Number.isInteger(l.n) || l.n > l.max);
  const save = useMutation({
    mutationFn: () => {
      const body = {
        reason,
        restock,
        refund_method: refund || null,
        items: chosen.map((l) => ({ invoice_item_id: l.it.id, quantity: l.n })),
      };
      return api.post(`/invoices/${invoice.id}/credit-notes`, body, submitter.keyFor(body));
    },
    onSuccess: () => {
      submitter.done();
      qc.invalidateQueries();
      toast("Credit note issued");
      onClose();
    },
  });
  const refundNeeded = save.error instanceof ApiError && save.error.code === "refund_required";
  return (
    <Modal
      open
      onClose={onClose}
      wide
      title={`Return / credit note · ${invoice.number}`}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" onClick={() => save.mutate()} loading={save.isPending} disabled={!chosen.length || invalid || reason.trim().length < 3}>
            Issue credit note
          </Button>
        </>
      }
    >
      <ErrorBanner error={save.error} className="mb-3" />
      <Table>
        <thead>
          <tr>
            <Th>Item</Th>
            <Th className="text-right">Returnable</Th>
            <Th className="text-right">Credit qty</Th>
          </tr>
        </thead>
        <tbody>
          {lines.map(({ it, max }) => (
            <tr key={it.id}>
              <Td>
                {it.product_name} <span className="text-xs text-ink-3">{it.sku}</span>
              </Td>
              <Td className="tabular text-right">{max}</Td>
              <Td className="text-right">
                <Input
                  type="number"
                  min={0}
                  max={max}
                  value={qty[it.id] ?? ""}
                  onChange={(e) => setQty((q) => ({ ...q, [it.id]: e.target.value }))}
                  className="tabular ml-auto h-8 w-20 text-right"
                  aria-label={`Credit quantity for ${it.product_name}`}
                />
              </Td>
            </tr>
          ))}
        </tbody>
      </Table>
      <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="Reason" className="sm:col-span-2">
          {(id) => <Textarea id={id} value={reason} onChange={(e) => setReason(e.target.value)} />}
        </Field>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={restock} onChange={(e) => setRestock(e.target.checked)} className="accent-[var(--accent)]" />
          Put returned items back in stock
        </label>
        <Field label="Refund method" hint={refundNeeded ? undefined : "Needed only if the credit exceeds what is unpaid"} error={refundNeeded ? "Choose how to refund the excess" : undefined}>
          {(id) => (
            <Select id={id} value={refund} onChange={(e) => setRefund(e.target.value as typeof refund)}>
              <option value="">No refund (reduce balance)</option>
              {MONEY_METHODS.map((m) => (
                <option key={m} value={m}>
                  Refund by {METHOD_LABEL[m]}
                </option>
              ))}
            </Select>
          )}
        </Field>
      </div>
    </Modal>
  );
}
