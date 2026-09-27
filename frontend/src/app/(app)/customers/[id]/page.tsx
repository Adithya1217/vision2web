"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, AlertTriangle, Pencil, ReceiptIndianRupee } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { PaymentBadge } from "@/components/badges";
import { CustomerFormModal } from "@/components/customer-forms";
import { useToast } from "@/components/toast";
import { Badge, Button, Card, CardHeader, ErrorBanner, Field, Input, Modal, PageHeader, Pagination, Select, Spinner, Table, Td, Th } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDate, formatDateTime, METHOD_LABEL, stateName } from "@/lib/format";
import { useSubmitter } from "@/lib/hooks";
import { formatINR, fromPaise, isMoney, toPaise } from "@/lib/money";
import type { Ledger, PaymentMethod } from "@/lib/types";

const ENTRY_LABEL = { invoice: "Invoice", payment: "Payment", credit_note: "Credit note", refund: "Refund" } as const;

export default function CustomerLedgerPage() {
  const { id } = useParams<{ id: string }>();
  const { me, can } = useAuth();
  const [page, setPage] = useState(1);
  const [paying, setPaying] = useState(false);
  const [editing, setEditing] = useState(false);
  const qc = useQueryClient();
  const ledger = useQuery({
    queryKey: ["ledger", id, page],
    queryFn: () => api.get<Ledger>(`/customers/${id}/ledger`, { page, page_size: 50 }),
  });
  if (ledger.isLoading) return <Spinner />;
  if (!ledger.data) return <ErrorBanner error={ledger.error ?? "Not found"} />;
  const l = ledger.data;
  const c = l.customer;
  const tz = me?.shop.timezone;

  return (
    <>
      <PageHeader
        title={c.name}
        subtitle={[c.phone, c.gstin && `GSTIN ${c.gstin}`, c.state_code && stateName(c.state_code)].filter(Boolean).join(" · ") || undefined}
        actions={
          <>
            {can("customers.write") && (
              <Button onClick={() => setEditing(true)}>
                <Pencil className="h-4 w-4" /> Edit
              </Button>
            )}
            {can("payments.record") && l.balance !== "0.00" && (
              <Button variant="primary" onClick={() => setPaying(true)}>
                <ReceiptIndianRupee className="h-4 w-4" /> Receive payment
              </Button>
            )}
          </>
        }
      />
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Khata balance" value={formatINR(l.balance)} />
        <Stat label="Overdue" value={formatINR(l.overdue_amount)} note={l.oldest_overdue_date ? `since ${formatDate(l.oldest_overdue_date)}` : undefined} />
        <Stat label="Open invoices" value={String(l.open_invoices.length)} />
        <Stat label="Credit limit" value={c.credit_limit ? formatINR(c.credit_limit) : "No limit"} />
      </div>
      <p className="mb-4 flex items-center gap-1.5 text-xs text-ink-3">
        {l.reconciled ? (
          <>
            <CheckCircle2 className="h-3.5 w-3.5 text-good-ink" aria-hidden /> Ledger reconciles with open invoice balances ({formatINR(l.invoice_outstanding)}).
          </>
        ) : (
          <>
            <AlertTriangle className="h-3.5 w-3.5 text-critical-ink" aria-hidden /> Ledger ({formatINR(l.balance)}) differs from open invoices ({formatINR(l.invoice_outstanding)}).
          </>
        )}
      </p>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader title="Ledger" subtitle="Newest first, with running balance" />
          <Table>
            <thead>
              <tr>
                <Th>Date</Th>
                <Th>Entry</Th>
                <Th className="text-right">Debit</Th>
                <Th className="text-right">Credit</Th>
                <Th className="text-right">Balance</Th>
              </tr>
            </thead>
            <tbody className="tabular">
              {l.entries.map((e) => (
                <tr key={e.id}>
                  <Td className="whitespace-nowrap text-ink-2">{formatDateTime(e.occurred_at, tz)}</Td>
                  <Td>
                    <Badge>{ENTRY_LABEL[e.entry_type]}</Badge>{" "}
                    {e.invoice_id ? (
                      <Link href={`/invoices/${e.invoice_id}`} className="text-sm hover:underline">
                        {e.description}
                      </Link>
                    ) : (
                      <span className="text-sm">{e.description}</span>
                    )}
                  </Td>
                  <Td className="text-right">{e.debit !== "0.00" ? formatINR(e.debit) : ""}</Td>
                  <Td className="text-right text-good-ink">{e.credit !== "0.00" ? formatINR(e.credit) : ""}</Td>
                  <Td className="text-right font-medium">{formatINR(e.running_balance)}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
          {l.entries.length === 0 && <p className="px-4 py-6 text-sm text-ink-3">No transactions yet.</p>}
          <Pagination page={page} pageSize={50} total={l.total_entries} onPage={setPage} />
        </Card>
        <Card>
          <CardHeader title="Open invoices" />
          <ul className="divide-y divide-line">
            {l.open_invoices.map((inv) => (
              <li key={inv.id} className="flex items-center justify-between gap-2 px-4 py-2.5 text-sm">
                <div>
                  <Link href={`/invoices/${inv.id}`} className="font-medium hover:underline">
                    {inv.number}
                  </Link>
                  <p className="text-xs text-ink-3">Due {formatDate(inv.due_date)}</p>
                </div>
                <div className="flex flex-col items-end gap-1">
                  <span className="tabular font-medium">{formatINR(inv.balance_due)}</span>
                  <PaymentBadge status={inv.payment_status} overdue={inv.is_overdue} />
                </div>
              </li>
            ))}
            {l.open_invoices.length === 0 && <li className="px-4 py-4 text-sm text-ink-3">Nothing outstanding.</li>}
          </ul>
        </Card>
      </div>
      {paying && <KhataPaymentModal customerId={c.id} balance={l.balance} onClose={() => setPaying(false)} />}
      {editing && (
        <CustomerFormModal
          open
          customer={c}
          onClose={() => setEditing(false)}
          onSaved={() => {
            setEditing(false);
            qc.invalidateQueries({ queryKey: ["ledger", id] });
          }}
        />
      )}
    </>
  );
}

function Stat({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <Card className="p-4">
      <p className="text-xs text-ink-3">{label}</p>
      <p className="mt-1 text-xl font-semibold">{value}</p>
      {note && <p className="text-xs text-ink-3">{note}</p>}
    </Card>
  );
}

function KhataPaymentModal({ customerId, balance, onClose }: { customerId: number; balance: string; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const submitter = useSubmitter();
  const [amount, setAmount] = useState(balance);
  const [method, setMethod] = useState<Exclude<PaymentMethod, "credit">>("cash");
  const [reference, setReference] = useState("");
  const tooMuch = isMoney(amount) && toPaise(amount) > toPaise(balance);
  const save = useMutation({
    mutationFn: () => {
      const body = { method, amount: fromPaise(toPaise(amount)), reference: reference || null };
      return api.post(`/customers/${customerId}/payments`, body, submitter.keyFor(body));
    },
    onSuccess: () => {
      submitter.done();
      qc.invalidateQueries();
      toast("Payment received");
      onClose();
    },
  });
  return (
    <Modal
      open
      onClose={onClose}
      title="Receive khata payment"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" loading={save.isPending} onClick={() => save.mutate()} disabled={!isMoney(amount) || toPaise(amount) <= 0n || tooMuch}>
            Save
          </Button>
        </>
      }
    >
      <ErrorBanner error={save.error} className="mb-3" />
      <p className="mb-3 text-sm text-ink-2">Allocated to the oldest open invoices first. Outstanding {formatINR(balance)}.</p>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="Amount (₹)" error={tooMuch ? "More than outstanding" : undefined}>
          {(id) => <Input id={id} value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="decimal" />}
        </Field>
        <Field label="Method">
          {(id) => (
            <Select id={id} value={method} onChange={(e) => setMethod(e.target.value as typeof method)}>
              {(["cash", "upi", "card", "bank_transfer"] as const).map((m) => (
                <option key={m} value={m}>
                  {METHOD_LABEL[m]}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="Reference" className="sm:col-span-2">
          {(id) => <Input id={id} value={reference} onChange={(e) => setReference(e.target.value)} />}
        </Field>
      </div>
    </Modal>
  );
}
