"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Minus, Plus, Trash2 } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useMemo, useState } from "react";

import { CustomerPicker } from "@/components/customer-forms";
import { useToast } from "@/components/toast";
import { Badge, Button, Card, CardHeader, ErrorBanner, Field, Input, PageHeader, Select, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { METHOD_LABEL, STATES, stateName } from "@/lib/format";
import { useDebounced, useSubmitter } from "@/lib/hooks";
import { estimateLine, formatINR, fromPaise, isMoney, toPaise } from "@/lib/money";
import type { Customer, Invoice, Page, PaymentMethod, Product } from "@/lib/types";

interface Line {
  product: Pick<Product, "id" | "name" | "sku" | "sale_price" | "gst_rate" | "quantity" | "unit">;
  quantity: number;
  discountPercent: string;
  unitPrice: string;
}

type PayMode = "full" | "partial" | "credit";

export default function NewInvoicePage() {
  return (
    <Suspense fallback={<Spinner />}>
      <InvoiceBuilder />
    </Suspense>
  );
}

function InvoiceBuilder() {
  const draftId = useSearchParams().get("draft");
  const existing = useQuery({
    queryKey: ["invoice", draftId],
    queryFn: () => api.get<Invoice>(`/invoices/${draftId}`),
    enabled: !!draftId,
  });
  const customerId = existing.data?.customer_id;
  const existingCustomer = useQuery({
    queryKey: ["customer", customerId],
    queryFn: () => api.get<Customer>(`/customers/${customerId}`),
    enabled: !!customerId,
  });
  if (draftId && (existing.isLoading || (customerId && existingCustomer.isLoading))) return <Spinner />;
  if (existing.error) return <ErrorBanner error={existing.error} />;
  if (existing.data && existing.data.status !== "draft")
    return <ErrorBanner error="This invoice is already posted and can no longer be edited." />;
  return <InvoiceForm key={draftId ?? "new"} draft={existing.data ?? null} draftCustomer={existingCustomer.data ?? null} />;
}

function InvoiceForm({ draft, draftCustomer }: { draft: Invoice | null; draftCustomer: Customer | null }) {
  const { me, can } = useAuth();
  const router = useRouter();
  const toast = useToast();
  const qc = useQueryClient();
  const draftSubmitter = useSubmitter();
  const postSubmitter = useSubmitter();

  const [lines, setLines] = useState<Line[]>(() =>
    (draft?.items ?? []).map((it) => ({
      product: { id: it.product_id, name: it.product_name, sku: it.sku, sale_price: it.unit_price, gst_rate: it.gst_rate, quantity: 0, unit: it.unit },
      quantity: it.quantity,
      discountPercent: "",
      unitPrice: it.unit_price,
    })),
  );
  const [customer, setCustomer] = useState<Customer | null>(draftCustomer);
  const [placeOfSupply, setPlaceOfSupply] = useState<string>(draft?.place_of_supply ?? "");
  const [notes, setNotes] = useState(draft?.notes ?? "");
  const [payMode, setPayMode] = useState<PayMode>("full");
  const [method, setMethod] = useState<Exclude<PaymentMethod, "credit">>("cash");
  const [partAmount, setPartAmount] = useState("");
  const [busy, setBusy] = useState<"draft" | "post" | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [savedDraft, setSavedDraft] = useState<Invoice | null>(draft);

  const shopState = me?.shop.state_code ?? "";
  const pos = placeOfSupply || customer?.state_code || shopState;
  const intra = pos === shopState;

  const totals = useMemo(() => {
    const t = { gross: 0n, discount: 0n, taxable: 0n, cgst: 0n, sgst: 0n, igst: 0n, total: 0n };
    const perLine = lines.map((l) => {
      const est = estimateLine(l.quantity, isMoney(l.unitPrice) ? l.unitPrice : "0", l.product.gst_rate, { percent: l.discountPercent || undefined }, intra);
      (Object.keys(t) as (keyof typeof t)[]).forEach((k) => (t[k] += est[k]));
      return est;
    });
    return { ...t, perLine };
  }, [lines, intra]);

  const addProduct = (p: Product) => {
    setLines((ls) => {
      const i = ls.findIndex((l) => l.product.id === p.id);
      if (i >= 0) return ls.map((l, j) => (j === i ? { ...l, quantity: l.quantity + 1 } : l));
      return [...ls, { product: p, quantity: 1, discountPercent: "", unitPrice: p.sale_price }];
    });
  };
  const update = (i: number, patch: Partial<Line>) => setLines((ls) => ls.map((l, j) => (j === i ? { ...l, ...patch } : l)));

  const draftBody = () => ({
    customer_id: customer?.id ?? null,
    place_of_supply: placeOfSupply || null,
    notes: notes || null,
    items: lines.map((l) => ({
      product_id: l.product.id,
      quantity: l.quantity,
      discount_percent: l.discountPercent ? l.discountPercent : null,
      unit_price: l.unitPrice !== l.product.sale_price && can("products.write") ? l.unitPrice : null,
    })),
  });

  const saveDraft = async (): Promise<Invoice> => {
    const body = draftBody();
    const key = draftSubmitter.keyFor({ id: savedDraft?.id, body });
    const inv = savedDraft
      ? await api.put<Invoice>(`/invoices/${savedDraft.id}`, body, key)
      : await api.post<Invoice>("/invoices", body, key);
    draftSubmitter.done();
    setSavedDraft(inv);
    return inv;
  };

  const onSaveDraft = async () => {
    setBusy("draft");
    setError(null);
    try {
      const inv = await saveDraft();
      toast("Draft saved");
      qc.invalidateQueries({ queryKey: ["invoices"] });
      router.push(`/invoices/${inv.id}`);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(null);
    }
  };

  const onPost = async () => {
    setBusy("post");
    setError(null);
    try {
      const draft = await saveDraft();
      // Payment amounts are taken from the server's totals, never from the client estimate.
      let payments: { method: string; amount: string }[] = [];
      if (payMode === "full") payments = [{ method, amount: draft.grand_total }];
      else if (payMode === "partial" && partAmount) payments = [{ method, amount: fromPaise(toPaise(partAmount)) }];
      const body = { payments };
      const posted = await api.post<Invoice>(`/invoices/${draft.id}/post`, body, postSubmitter.keyFor({ id: draft.id, body }));
      postSubmitter.done();
      qc.invalidateQueries();
      toast(`Posted ${posted.number}`);
      router.push(`/invoices/${posted.id}`);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(null);
    }
  };

  const partInvalid = payMode === "partial" && (!isMoney(partAmount) || toPaise(partAmount) <= 0n);
  const needsCustomer = payMode !== "full" && !customer;

  return (
    <>
      <PageHeader title={savedDraft ? `Edit draft #${savedDraft.id}` : "New invoice"} subtitle="Stock is checked and deducted only when you post." />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="flex flex-col gap-4 lg:col-span-2">
          <Card>
            <CardHeader title="Items" />
            <div className="p-3">
              <ProductPicker onPick={addProduct} />
            </div>
            {lines.length === 0 ? (
              <p className="px-4 pb-6 text-sm text-ink-3">Search above to add products.</p>
            ) : (
              <ul className="divide-y divide-line">
                {lines.map((l, i) => {
                  const est = totals.perLine[i];
                  const short = l.product.quantity > 0 && l.quantity > l.product.quantity;
                  return (
                    <li key={l.product.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
                      <div className="min-w-40 flex-1">
                        <p className="font-medium">{l.product.name}</p>
                        <p className="text-xs text-ink-3">
                          {l.product.sku} · GST {Number(l.product.gst_rate)}%
                          {l.product.quantity > 0 && ` · ${l.product.quantity} in stock`}
                        </p>
                        {short && <Badge tone="warning">Only {l.product.quantity} in stock</Badge>}
                      </div>
                      <div className="flex items-center gap-1">
                        <Button size="sm" variant="ghost" aria-label="Decrease" onClick={() => update(i, { quantity: Math.max(1, l.quantity - 1) })}>
                          <Minus className="h-3.5 w-3.5" />
                        </Button>
                        <Input
                          type="number"
                          min={1}
                          value={l.quantity}
                          onChange={(e) => update(i, { quantity: Math.max(1, Number(e.target.value) || 1) })}
                          className="tabular h-8 w-16 text-center"
                          aria-label={`Quantity of ${l.product.name}`}
                        />
                        <Button size="sm" variant="ghost" aria-label="Increase" onClick={() => update(i, { quantity: l.quantity + 1 })}>
                          <Plus className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                      <Input
                        value={l.unitPrice}
                        disabled={!can("products.write")}
                        onChange={(e) => update(i, { unitPrice: e.target.value })}
                        className="tabular h-8 w-24 text-right"
                        aria-label="Unit price"
                        title={can("products.write") ? "Unit price (override)" : "Only managers can change prices"}
                      />
                      <div className="flex items-center gap-1">
                        <Input
                          value={l.discountPercent}
                          onChange={(e) => update(i, { discountPercent: e.target.value })}
                          placeholder="0"
                          className="tabular h-8 w-14 text-right"
                          aria-label="Discount percent"
                        />
                        <span className="text-xs text-ink-3">% off</span>
                      </div>
                      <p className="tabular w-24 text-right font-medium">{formatINR(fromPaise(est.total))}</p>
                      <Button size="sm" variant="ghost" aria-label={`Remove ${l.product.name}`} onClick={() => setLines((ls) => ls.filter((_, j) => j !== i))}>
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </li>
                  );
                })}
              </ul>
            )}
          </Card>
          <Card>
            <CardHeader title="Customer" subtitle="Needed for credit (khata) sales and B2B GST invoices" />
            <div className="grid grid-cols-1 gap-3 p-4 sm:grid-cols-2">
              <CustomerPicker value={customer} onChange={setCustomer} />
              <Field label="Place of supply" hint={intra ? "Intra-state: CGST + SGST" : "Inter-state: IGST"}>
                {(id) => (
                  <Select id={id} value={placeOfSupply} onChange={(e) => setPlaceOfSupply(e.target.value)}>
                    <option value="">Auto ({stateName(customer?.state_code || shopState)})</option>
                    {STATES.map(([c, n]) => (
                      <option key={c} value={c}>
                        {c} · {n}
                      </option>
                    ))}
                  </Select>
                )}
              </Field>
              <Field label="Notes" className="sm:col-span-2">
                {(id) => <Input id={id} value={notes} onChange={(e) => setNotes(e.target.value)} />}
              </Field>
            </div>
          </Card>
        </div>

        <div className="flex flex-col gap-4">
          <Card className="lg:sticky lg:top-20">
            <CardHeader title="Summary" subtitle="Estimate — the server calculates the final amounts" />
            <dl className="tabular flex flex-col gap-1.5 px-4 py-3 text-sm">
              <Row label="Subtotal" value={totals.gross} />
              <Row label="Discount" value={-totals.discount} />
              <Row label="Taxable value" value={totals.taxable} />
              {intra ? (
                <>
                  <Row label="CGST" value={totals.cgst} />
                  <Row label="SGST" value={totals.sgst} />
                </>
              ) : (
                <Row label="IGST" value={totals.igst} />
              )}
              <div className="mt-1 flex justify-between border-t border-line pt-2 text-base font-semibold">
                <dt>Total</dt>
                <dd>{formatINR(fromPaise(totals.total))}</dd>
              </div>
            </dl>
            <div className="flex flex-col gap-3 border-t border-line px-4 py-3">
              <fieldset className="flex flex-col gap-1.5">
                <legend className="mb-1 text-xs font-medium text-ink-2">Payment</legend>
                {(
                  [
                    ["full", "Paid in full"],
                    ["partial", "Part payment, rest on khata"],
                    ["credit", "Full credit (khata)"],
                  ] as [PayMode, string][]
                ).map(([v, label]) => (
                  <label key={v} className="flex items-center gap-2 text-sm">
                    <input type="radio" name="paymode" checked={payMode === v} onChange={() => setPayMode(v)} className="accent-[var(--accent)]" />
                    {label}
                  </label>
                ))}
              </fieldset>
              {payMode !== "credit" && (
                <div className="grid grid-cols-2 gap-2">
                  <Select value={method} onChange={(e) => setMethod(e.target.value as typeof method)} aria-label="Payment method">
                    {(["cash", "upi", "card", "bank_transfer"] as const).map((m) => (
                      <option key={m} value={m}>
                        {METHOD_LABEL[m]}
                      </option>
                    ))}
                  </Select>
                  {payMode === "partial" && (
                    <Input inputMode="decimal" placeholder="Amount" value={partAmount} onChange={(e) => setPartAmount(e.target.value)} aria-label="Amount received" />
                  )}
                </div>
              )}
              {needsCustomer && <p className="text-xs text-warning-ink">Select a customer to sell on credit.</p>}
              <ErrorBanner error={error} />
              <Button variant="primary" onClick={onPost} loading={busy === "post"} disabled={!lines.length || !!busy || partInvalid || needsCustomer}>
                Post invoice
              </Button>
              <Button onClick={onSaveDraft} loading={busy === "draft"} disabled={!lines.length || !!busy}>
                Save as draft
              </Button>
            </div>
          </Card>
        </div>
      </div>
    </>
  );
}

function Row({ label, value }: { label: string; value: bigint }) {
  return (
    <div className="flex justify-between text-ink-2">
      <dt>{label}</dt>
      <dd className="text-ink">{formatINR(fromPaise(value))}</dd>
    </div>
  );
}

function ProductPicker({ onPick }: { onPick: (p: Product) => void }) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const search = useDebounced(q, 200);
  const results = useQuery({
    queryKey: ["products", "picker", search],
    queryFn: () => api.get<Page<Product>>("/products", { q: search, page_size: 8 }),
    enabled: search.length > 0,
  });
  return (
    <div className="relative">
      <Input
        value={q}
        onChange={(e) => {
          setQ(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        placeholder="Search product by name or SKU…"
        aria-label="Add product"
      />
      {open && search && (
        <ul className="absolute z-20 mt-1 max-h-72 w-full overflow-auto rounded-lg border border-line bg-surface shadow-lg" role="listbox">
          {results.data?.items.length === 0 && <li className="px-3 py-2 text-sm text-ink-3">No matches</li>}
          {results.data?.items.map((p) => (
            <li key={p.id}>
              <button
                type="button"
                className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm hover:bg-surface-2 disabled:opacity-50"
                onMouseDown={(e) => e.preventDefault()}
                disabled={p.quantity <= 0}
                onClick={() => {
                  onPick(p);
                  setQ("");
                  setOpen(false);
                }}
              >
                <span>
                  <span className="font-medium">{p.name}</span> <span className="text-xs text-ink-3">{p.sku}</span>
                </span>
                <span className="tabular text-xs text-ink-2">
                  {formatINR(p.sale_price)} · {p.quantity > 0 ? `${p.quantity} left` : "out of stock"}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
