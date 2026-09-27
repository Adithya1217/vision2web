"use client";

import { useQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { CustomerFormModal } from "@/components/customer-forms";
import { Badge, Button, Card, EmptyState, ErrorBanner, PageHeader, Pagination, SearchInput, Select, Spinner, Table, Td, Th } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useDebounced } from "@/lib/hooks";
import { formatINR } from "@/lib/money";
import type { Customer, Page } from "@/lib/types";

export default function CustomersPage() {
  return (
    <Suspense fallback={<Spinner />}>
      <CustomersPageInner />
    </Suspense>
  );
}

function CustomersPageInner() {
  const initial = useSearchParams().get("filter") ?? "";
  const { can } = useAuth();
  const router = useRouter();
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState(initial);
  const [sort, setSort] = useState("name");
  const [page, setPage] = useState(1);
  const [adding, setAdding] = useState(false);
  const search = useDebounced(q);
  const params = {
    q: search,
    has_balance: filter === "balance" ? "true" : "",
    overdue: filter === "overdue" ? "true" : "",
    sort,
    page,
    page_size: 25,
  };
  const list = useQuery({ queryKey: ["customers", params], queryFn: () => api.get<Page<Customer>>("/customers", params) });

  return (
    <>
      <PageHeader
        title="Customers & khata"
        subtitle="Balances are computed from each customer's ledger, not stored separately."
        actions={
          can("customers.write") && (
            <Button variant="primary" onClick={() => setAdding(true)}>
              <Plus className="h-4 w-4" /> Add customer
            </Button>
          )
        }
      />
      <Card>
        <div className="flex flex-wrap items-center gap-2 border-b border-line p-3">
          <SearchInput value={q} onChange={(v) => { setQ(v); setPage(1); }} placeholder="Name, phone or email" />
          <Select value={filter} onChange={(e) => { setFilter(e.target.value); setPage(1); }} className="w-auto" aria-label="Filter">
            <option value="">All customers</option>
            <option value="balance">With khata balance</option>
            <option value="overdue">Overdue</option>
          </Select>
          <Select value={sort} onChange={(e) => { setSort(e.target.value); setPage(1); }} className="w-auto sm:ml-auto" aria-label="Sort">
            <option value="name">Name</option>
            <option value="-balance">Highest balance</option>
            <option value="-overdue">Most overdue</option>
            <option value="-created_at">Newest</option>
          </Select>
        </div>
        <ErrorBanner error={list.error} className="m-3" />
        {list.isLoading ? (
          <Spinner />
        ) : !list.data?.items.length ? (
          <EmptyState title="No customers found" />
        ) : (
          <>
            <Table>
              <thead>
                <tr>
                  <Th>Customer</Th>
                  <Th className="hidden md:table-cell">GSTIN</Th>
                  <Th className="text-right">Balance</Th>
                  <Th className="text-right">Overdue</Th>
                </tr>
              </thead>
              <tbody>
                {list.data.items.map((c) => (
                  <tr key={c.id} className="cursor-pointer hover:bg-lavender-soft" onClick={() => router.push(`/customers/${c.id}`)}>
                    <Td>
                      <Link href={`/customers/${c.id}`} className="font-medium hover:underline" onClick={(e) => e.stopPropagation()}>
                        {c.name}
                      </Link>
                      <p className="text-xs text-ink-3">{c.phone ?? "—"}</p>
                    </Td>
                    <Td className="hidden text-ink-2 md:table-cell">{c.gstin ?? "—"}</Td>
                    <Td className="tabular text-right font-medium">{formatINR(c.balance)}</Td>
                    <Td className="text-right">
                      {c.overdue_amount !== "0.00" ? <Badge tone="critical">{formatINR(c.overdue_amount)}</Badge> : <span className="text-ink-3">—</span>}
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
            <Pagination page={page} pageSize={25} total={list.data.total} onPage={setPage} />
          </>
        )}
      </Card>
      {adding && <CustomerFormModal open onClose={() => setAdding(false)} onSaved={(c) => router.push(`/customers/${c.id}`)} />}
    </>
  );
}
