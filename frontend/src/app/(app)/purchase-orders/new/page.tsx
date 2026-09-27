"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { useToast } from "@/components/toast";
import { Button, Card, CardHeader, ErrorBanner, Field, Input, PageHeader, Select } from "@/components/ui";
import { api } from "@/lib/api";
import { useDebounced, useSubmitter } from "@/lib/hooks";
import { divRound, formatINR, fromPaise, isMoney, toPaise } from "@/lib/money";
import type { Page, Product, PurchaseOrder, Supplier } from "@/lib/types";

interface Line {
  product: Product;
  quantity: number;
  unitCost: string;
}

export default function NewPurchaseOrderPage() {
  const router = useRouter();
  const toast = useToast();
  const qc = useQueryClient();
  const submitter = useSubmitter();
  const [supplierId, setSupplierId] = useState("");
  const [expected, setExpected] = useState("");
  const [notes, setNotes] = useState("");
  const [lines, setLines] = useState<Line[]>([]);
  const [q, setQ] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const search = useDebounced(q, 200);
  const suppliers = useQuery({ queryKey: ["suppliers", "all"], queryFn: () => api.get<Page<Supplier>>("/suppliers", { page_size: 200 }) });
  const products = useQuery({
    queryKey: ["products", "po-picker", search],
    queryFn: () => api.get<Page<Product>>("/products", { q: search, page_size: 8 }),
    enabled: !!search,
  });

  const lineTotal = (l: Line) => {
    if (!isMoney(l.unitCost)) return 0n;
    const sub = toPaise(l.unitCost) * BigInt(l.quantity);
    return sub + divRound(sub * toPaise(l.product.gst_rate), 10000n);
  };
  const total = lines.reduce((s, l) => s + lineTotal(l), 0n);
  const valid = supplierId && lines.length && lines.every((l) => l.quantity > 0 && isMoney(l.unitCost));

  const save = async (send: boolean) => {
    setBusy(true);
    setError(null);
    const body = {
      supplier_id: Number(supplierId),
      expected_date: expected || null,
      notes: notes || null,
      items: lines.map((l) => ({ product_id: l.product.id, quantity: l.quantity, unit_cost: fromPaise(toPaise(l.unitCost)) })),
    };
    try {
      const po = await api.post<PurchaseOrder>("/purchase-orders", body, submitter.keyFor(body));
      submitter.done();
      if (send) await api.post(`/purchase-orders/${po.id}/send`);
      qc.invalidateQueries({ queryKey: ["purchase-orders"] });
      toast(`${po.number} ${send ? "created and marked sent" : "saved as draft"}`);
      router.push(`/purchase-orders/${po.id}`);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PageHeader title="New purchase order" />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader title="Items" subtitle="Unit cost excludes GST" />
          <div className="relative p-3">
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search product to add…" aria-label="Add product" />
            {search && products.data && (
              <ul className="absolute left-3 right-3 z-10 mt-1 max-h-60 overflow-auto rounded-sm border-2 border-line-strong bg-surface shadow-md">
                {products.data.items.map((p) => (
                  <li key={p.id}>
                    <button
                      className="flex w-full justify-between px-3 py-2 text-left text-sm hover:bg-lavender-soft"
                      onClick={() => {
                        if (!lines.some((l) => l.product.id === p.id))
                          setLines((ls) => [...ls, { product: p, quantity: p.reorder_quantity || 1, unitCost: p.cost_price ?? "" }]);
                        setQ("");
                      }}
                    >
                      <span>
                        {p.name} <span className="text-xs text-ink-3">{p.sku}</span>
                      </span>
                      <span className="text-xs text-ink-3">{p.quantity} in stock</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <ul className="divide-y divide-line">
            {lines.map((l, i) => (
              <li key={l.product.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
                <div className="min-w-40 flex-1">
                  <p className="font-medium">{l.product.name}</p>
                  <p className="text-xs text-ink-3">
                    {l.product.sku} · GST {Number(l.product.gst_rate)}%
                  </p>
                </div>
                <Input
                  type="number"
                  min={1}
                  value={l.quantity}
                  onChange={(e) => setLines((ls) => ls.map((x, j) => (j === i ? { ...x, quantity: Math.max(1, Number(e.target.value) || 1) } : x)))}
                  className="tabular h-8 w-20 text-right"
                  aria-label="Quantity"
                />
                <Input
                  value={l.unitCost}
                  placeholder="Unit cost"
                  onChange={(e) => setLines((ls) => ls.map((x, j) => (j === i ? { ...x, unitCost: e.target.value } : x)))}
                  className="tabular h-8 w-28 text-right"
                  aria-label="Unit cost"
                />
                <span className="tabular w-24 text-right">{formatINR(fromPaise(lineTotal(l)))}</span>
                <Button size="sm" variant="ghost" onClick={() => setLines((ls) => ls.filter((_, j) => j !== i))} aria-label="Remove">
                  <Trash2 className="h-4 w-4" />
                </Button>
              </li>
            ))}
          </ul>
          {!lines.length && <p className="px-4 pb-6 text-sm text-ink-3">Add products to order.</p>}
        </Card>
        <Card className="h-fit">
          <CardHeader title="Order" />
          <div className="flex flex-col gap-3 p-4">
            <Field label="Supplier">
              {(id) => (
                <Select id={id} value={supplierId} onChange={(e) => setSupplierId(e.target.value)}>
                  <option value="">Select supplier</option>
                  {suppliers.data?.items.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <Field label="Expected delivery">{(id) => <Input id={id} type="date" value={expected} onChange={(e) => setExpected(e.target.value)} />}</Field>
            <Field label="Notes">{(id) => <Input id={id} value={notes} onChange={(e) => setNotes(e.target.value)} />}</Field>
            <p className="flex justify-between border-t border-line pt-3 font-semibold">
              <span>Estimated total</span>
              <span className="tabular">{formatINR(fromPaise(total))}</span>
            </p>
            <ErrorBanner error={error} />
            <Button variant="primary" disabled={!valid} loading={busy} onClick={() => save(true)}>
              Create &amp; mark sent
            </Button>
            <Button disabled={!valid || busy} onClick={() => save(false)}>
              Save draft
            </Button>
          </div>
        </Card>
      </div>
    </>
  );
}
