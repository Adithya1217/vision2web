"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { Badge, Card, EmptyState, ErrorBanner, Input, PageHeader, Pagination, SearchInput, Select, Spinner, Table, Td, Th } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDateTime, MOVEMENT_LABEL } from "@/lib/format";
import { useDebounced } from "@/lib/hooks";
import type { MovementType, Page, StockMovement } from "@/lib/types";

export default function InventoryPage() {
  const { me } = useAuth();
  const [q, setQ] = useState("");
  const [type, setType] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [page, setPage] = useState(1);
  const search = useDebounced(q);
  const params = { q: search, movement_type: type, start_date: start, end_date: end, page, page_size: 50 };
  const list = useQuery({
    queryKey: ["movements", params],
    queryFn: () => api.get<Page<StockMovement>>("/inventory/movements", params),
  });

  const refLink = (m: StockMovement) => {
    if (m.reference_type === "invoice" && m.reference_id) return `/invoices/${m.reference_id}`;
    if (m.reference_type === "purchase_order" && m.reference_id) return `/purchase-orders/${m.reference_id}`;
    return null;
  };

  return (
    <>
      <PageHeader
        title="Stock movements"
        subtitle="An append-only record of every change to stock. Adjust stock from the Products page."
      />
      <Card>
        <div className="flex flex-wrap items-center gap-2 border-b border-line p-3">
          <SearchInput value={q} onChange={(v) => { setQ(v); setPage(1); }} placeholder="Product, SKU or reason" />
          <Select value={type} onChange={(e) => { setType(e.target.value); setPage(1); }} className="w-auto" aria-label="Movement type">
            <option value="">All types</option>
            {(Object.keys(MOVEMENT_LABEL) as MovementType[]).map((t) => (
              <option key={t} value={t}>
                {MOVEMENT_LABEL[t]}
              </option>
            ))}
          </Select>
          <Input type="date" value={start} onChange={(e) => { setStart(e.target.value); setPage(1); }} className="w-auto" aria-label="From date" />
          <Input type="date" value={end} onChange={(e) => { setEnd(e.target.value); setPage(1); }} className="w-auto" aria-label="To date" />
        </div>
        <ErrorBanner error={list.error} className="m-3" />
        {list.isLoading ? (
          <Spinner />
        ) : !list.data?.items.length ? (
          <EmptyState title="No movements" hint="Stock changes from sales, receipts, returns and adjustments appear here." />
        ) : (
          <>
            <Table>
              <thead>
                <tr>
                  <Th>When</Th>
                  <Th>Product</Th>
                  <Th>Type</Th>
                  <Th className="text-right">Change</Th>
                  <Th className="text-right">Balance</Th>
                  <Th className="hidden md:table-cell">Reason / reference</Th>
                </tr>
              </thead>
              <tbody>
                {list.data.items.map((m) => {
                  const href = refLink(m);
                  return (
                    <tr key={m.id}>
                      <Td className="whitespace-nowrap text-ink-2">{formatDateTime(m.created_at, me?.shop.timezone)}</Td>
                      <Td>
                        <p className="font-medium">{m.product_name}</p>
                        <p className="text-xs text-ink-3">{m.sku}</p>
                      </Td>
                      <Td>
                        <Badge>{MOVEMENT_LABEL[m.movement_type]}</Badge>
                      </Td>
                      <Td className={`tabular text-right font-medium ${m.quantity_delta > 0 ? "text-good-ink" : "text-critical-ink"}`}>
                        {m.quantity_delta > 0 ? `+${m.quantity_delta}` : m.quantity_delta}
                      </Td>
                      <Td className="tabular text-right">{m.balance_after}</Td>
                      <Td className="hidden max-w-xs truncate text-ink-2 md:table-cell">
                        {href ? (
                          <Link href={href} className="text-info hover:underline">
                            {m.reason}
                          </Link>
                        ) : (
                          m.reason ?? "—"
                        )}
                      </Td>
                    </tr>
                  );
                })}
              </tbody>
            </Table>
            <Pagination page={page} pageSize={50} total={list.data.total} onPage={setPage} />
          </>
        )}
      </Card>
    </>
  );
}
