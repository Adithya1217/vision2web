"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { PackageCheck, Send, XCircle } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { POStatusBadge } from "@/components/badges";
import { useToast } from "@/components/toast";
import { Button, Card, CardHeader, ErrorBanner, Input, Modal, Spinner, Table, Td, Th } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDate } from "@/lib/format";
import { useSubmitter } from "@/lib/hooks";
import { formatINR } from "@/lib/money";
import type { PurchaseOrder } from "@/lib/types";

export default function PurchaseOrderPage() {
  const { id } = useParams<{ id: string }>();
  const { can } = useAuth();
  const qc = useQueryClient();
  const toast = useToast();
  const [receiving, setReceiving] = useState(false);
  const po = useQuery({ queryKey: ["purchase-order", id], queryFn: () => api.get<PurchaseOrder>(`/purchase-orders/${id}`) });
  const action = useMutation({
    mutationFn: (verb: "send" | "cancel") => api.post<PurchaseOrder>(`/purchase-orders/${id}/${verb}`),
    onSuccess: (p) => {
      qc.invalidateQueries({ queryKey: ["purchase-order", id] });
      qc.invalidateQueries({ queryKey: ["purchase-orders"] });
      toast(`${p.number} is now ${p.status}`);
    },
  });
  if (po.isLoading) return <Spinner />;
  if (!po.data) return <ErrorBanner error={po.error ?? "Not found"} />;
  const d = po.data;
  const outstanding = (d.items ?? []).some((i) => i.received_quantity < i.ordered_quantity);

  return (
    <>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Link href="/purchase-orders" className="font-mono text-sm text-ink-3 hover:text-ink">
            Purchase orders
          </Link>
          <span className="text-ink-3">/</span>
          <h1 className="font-pixel text-sm leading-6 sm:text-base">{d.number}</h1>
          <POStatusBadge status={d.status} />
        </div>
        <div className="flex flex-wrap gap-2">
          {can("purchase_orders.manage") && d.status === "draft" && (
            <Button variant="primary" onClick={() => action.mutate("send")} loading={action.isPending}>
              <Send className="h-4 w-4" /> Mark sent
            </Button>
          )}
          {can("purchase_orders.receive") && (d.status === "sent" || d.status === "partial") && outstanding && (
            <Button variant="primary" onClick={() => setReceiving(true)}>
              <PackageCheck className="h-4 w-4" /> Receive stock
            </Button>
          )}
          {can("purchase_orders.manage") && (d.status === "draft" || d.status === "sent") && (
            <Button variant="ghost" onClick={() => action.mutate("cancel")} loading={action.isPending}>
              <XCircle className="h-4 w-4" /> Cancel order
            </Button>
          )}
        </div>
      </div>
      <ErrorBanner error={action.error} className="mb-3" />
      <Card>
        <CardHeader
          title={d.supplier_name ?? "Supplier"}
          subtitle={`Ordered ${formatDate(d.order_date)}${d.expected_date ? ` · expected ${formatDate(d.expected_date)}` : ""}`}
        />
        <Table>
          <thead>
            <tr>
              <Th>Item</Th>
              <Th className="text-right">Ordered</Th>
              <Th className="text-right">Received</Th>
              <Th className="text-right">Unit cost</Th>
              <Th className="hidden text-right sm:table-cell">GST</Th>
              <Th className="text-right">Total</Th>
            </tr>
          </thead>
          <tbody className="tabular">
            {d.items?.map((it) => (
              <tr key={it.id}>
                <Td>
                  {it.product_name} <span className="text-xs text-ink-3">{it.sku}</span>
                </Td>
                <Td className="text-right">{it.ordered_quantity}</Td>
                <Td className={`text-right ${it.received_quantity === it.ordered_quantity ? "text-good-ink" : ""}`}>{it.received_quantity}</Td>
                <Td className="text-right">{formatINR(it.unit_cost)}</Td>
                <Td className="hidden text-right sm:table-cell">{formatINR(it.line_tax)}</Td>
                <Td className="text-right">{formatINR(it.line_total)}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
        <dl className="tabular ml-auto flex max-w-xs flex-col gap-1 p-4 text-sm">
          <div className="flex justify-between text-ink-2">
            <dt>Subtotal</dt>
            <dd>{formatINR(d.subtotal)}</dd>
          </div>
          <div className="flex justify-between text-ink-2">
            <dt>GST</dt>
            <dd>{formatINR(d.tax_total)}</dd>
          </div>
          <div className="flex justify-between font-semibold">
            <dt>Total</dt>
            <dd>{formatINR(d.total)}</dd>
          </div>
        </dl>
        {d.notes && <p className="border-t border-line px-4 py-3 text-sm text-ink-2">{d.notes}</p>}
      </Card>
      {receiving && <ReceiveModal po={d} onClose={() => setReceiving(false)} />}
    </>
  );
}

function ReceiveModal({ po, onClose }: { po: PurchaseOrder; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const submitter = useSubmitter();
  const open = (po.items ?? []).filter((i) => i.received_quantity < i.ordered_quantity);
  const [qty, setQty] = useState<Record<number, string>>(() =>
    Object.fromEntries(open.map((i) => [i.id, String(i.ordered_quantity - i.received_quantity)])),
  );
  const [updateCost, setUpdateCost] = useState(true);
  const chosen = open.map((i) => ({ i, n: Number(qty[i.id] || 0) })).filter((x) => x.n > 0);
  const invalid = chosen.some(({ i, n }) => !Number.isInteger(n) || n > i.ordered_quantity - i.received_quantity);
  const save = useMutation({
    mutationFn: () => {
      const body = { update_cost_price: updateCost, items: chosen.map(({ i, n }) => ({ purchase_order_item_id: i.id, quantity: n })) };
      return api.post(`/purchase-orders/${po.id}/receipts`, body, submitter.keyFor(body));
    },
    onSuccess: () => {
      submitter.done();
      qc.invalidateQueries();
      toast("Stock received");
      onClose();
    },
  });
  return (
    <Modal
      open
      onClose={onClose}
      title={`Receive stock · ${po.number}`}
      wide
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" onClick={() => save.mutate()} loading={save.isPending} disabled={!chosen.length || invalid}>
            Receive {chosen.reduce((s, x) => s + x.n, 0)} units
          </Button>
        </>
      }
    >
      <ErrorBanner error={save.error} className="mb-3" />
      <Table>
        <thead>
          <tr>
            <Th>Item</Th>
            <Th className="text-right">Outstanding</Th>
            <Th className="text-right">Receiving now</Th>
          </tr>
        </thead>
        <tbody>
          {open.map((i) => (
            <tr key={i.id}>
              <Td>{i.product_name}</Td>
              <Td className="tabular text-right">{i.ordered_quantity - i.received_quantity}</Td>
              <Td className="text-right">
                <Input
                  type="number"
                  min={0}
                  max={i.ordered_quantity - i.received_quantity}
                  value={qty[i.id] ?? ""}
                  onChange={(e) => setQty((q) => ({ ...q, [i.id]: e.target.value }))}
                  className="tabular ml-auto h-8 w-20 text-right"
                  aria-label={`Receive quantity for ${i.product_name}`}
                />
              </Td>
            </tr>
          ))}
        </tbody>
      </Table>
      <label className="mt-3 flex items-center gap-2 text-sm">
        <input type="checkbox" checked={updateCost} onChange={(e) => setUpdateCost(e.target.checked)} className="accent-[var(--info)]" />
        Update product cost price to this order&apos;s unit cost
      </label>
    </Modal>
  );
}
