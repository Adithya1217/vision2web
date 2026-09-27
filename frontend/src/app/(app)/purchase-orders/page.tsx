"use client";

import { useQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { POStatusBadge } from "@/components/badges";
import { Button, Card, EmptyState, ErrorBanner, PageHeader, Pagination, SearchInput, Select, Spinner, Table, Td, Th } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDate } from "@/lib/format";
import { useDebounced } from "@/lib/hooks";
import { formatINR } from "@/lib/money";
import type { Page, PurchaseOrder } from "@/lib/types";

export default function PurchaseOrdersPage() {
  const { can } = useAuth();
  const router = useRouter();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const search = useDebounced(q);
  const params = { q: search, status: status === "pending" ? "" : status, pending: status === "pending" ? "true" : "", page, page_size: 25 };
  const list = useQuery({ queryKey: ["purchase-orders", params], queryFn: () => api.get<Page<PurchaseOrder>>("/purchase-orders", params) });
  return (
    <>
      <PageHeader
        title="Purchase orders"
        subtitle="Receiving stock against an order creates purchase-receipt movements. Cancelled orders never count as purchases."
        actions={
          can("purchase_orders.manage") && (
            <Link href="/purchase-orders/new">
              <Button variant="primary">
                <Plus className="h-4 w-4" /> New order
              </Button>
            </Link>
          )
        }
      />
      <Card>
        <div className="flex flex-wrap gap-2 border-b border-line p-3">
          <SearchInput value={q} onChange={(v) => { setQ(v); setPage(1); }} placeholder="PO number or supplier" />
          <Select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }} className="w-auto" aria-label="Status">
            <option value="">All</option>
            <option value="pending">Pending (sent or partial)</option>
            <option value="draft">Draft</option>
            <option value="sent">Sent</option>
            <option value="partial">Partially received</option>
            <option value="received">Received</option>
            <option value="cancelled">Cancelled</option>
          </Select>
        </div>
        <ErrorBanner error={list.error} className="m-3" />
        {list.isLoading ? (
          <Spinner />
        ) : !list.data?.items.length ? (
          <EmptyState title="No purchase orders" />
        ) : (
          <>
            <Table>
              <thead>
                <tr>
                  <Th>Order</Th>
                  <Th>Supplier</Th>
                  <Th className="hidden sm:table-cell">Date</Th>
                  <Th className="text-right">Total</Th>
                  <Th>Status</Th>
                </tr>
              </thead>
              <tbody>
                {list.data.items.map((po) => (
                  <tr key={po.id} className="cursor-pointer hover:bg-surface-2" onClick={() => router.push(`/purchase-orders/${po.id}`)}>
                    <Td>
                      <Link href={`/purchase-orders/${po.id}`} className="font-medium hover:underline" onClick={(e) => e.stopPropagation()}>
                        {po.number}
                      </Link>
                    </Td>
                    <Td className="text-ink-2">{po.supplier_name}</Td>
                    <Td className="hidden text-ink-2 sm:table-cell">{formatDate(po.order_date)}</Td>
                    <Td className="tabular text-right">{formatINR(po.total)}</Td>
                    <Td>
                      <POStatusBadge status={po.status} />
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
            <Pagination page={page} pageSize={25} total={list.data.total} onPage={setPage} />
          </>
        )}
      </Card>
    </>
  );
}
