"use client";

import { useQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { InvoiceStatusBadge, PaymentBadge } from "@/components/badges";
import { Button, Card, EmptyState, ErrorBanner, Input, PageHeader, Pagination, SearchInput, Select, Spinner, Table, Td, Th } from "@/components/ui";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { useDebounced } from "@/lib/hooks";
import { formatINR } from "@/lib/money";
import type { InvoiceSummary, Page } from "@/lib/types";

export default function InvoicesPage() {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [payment, setPayment] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [sort, setSort] = useState("-created_at");
  const [page, setPage] = useState(1);
  const search = useDebounced(q);
  const overdue = payment === "overdue";
  const params = {
    q: search,
    status,
    payment_status: overdue ? "" : payment,
    overdue: overdue ? "true" : "",
    start_date: start,
    end_date: end,
    sort,
    page,
    page_size: 25,
  };
  const list = useQuery({ queryKey: ["invoices", params], queryFn: () => api.get<Page<InvoiceSummary>>("/invoices", params) });
  const change = (fn: (v: string) => void) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    fn(e.target.value);
    setPage(1);
  };

  return (
    <>
      <PageHeader
        title="Invoices"
        subtitle="Drafts can be edited; posted invoices are final and corrected only by credit notes."
        actions={
          <Link href="/invoices/new">
            <Button variant="primary">
              <Plus className="h-4 w-4" /> New invoice
            </Button>
          </Link>
        }
      />
      <Card>
        <div className="flex flex-wrap items-center gap-2 border-b border-line p-3">
          <SearchInput value={q} onChange={(v) => { setQ(v); setPage(1); }} placeholder="Number, customer or phone" />
          <Select value={status} onChange={change(setStatus)} className="w-auto" aria-label="Status">
            <option value="">All statuses</option>
            <option value="draft">Draft</option>
            <option value="posted">Posted</option>
            <option value="cancelled">Cancelled</option>
          </Select>
          <Select value={payment} onChange={change(setPayment)} className="w-auto" aria-label="Payment">
            <option value="">Any payment</option>
            <option value="paid">Paid</option>
            <option value="partial">Partially paid</option>
            <option value="unpaid">Unpaid</option>
            <option value="overdue">Overdue</option>
          </Select>
          <Input type="date" value={start} onChange={change(setStart)} className="w-auto" aria-label="From" />
          <Input type="date" value={end} onChange={change(setEnd)} className="w-auto" aria-label="To" />
          <Select value={sort} onChange={change(setSort)} className="w-auto sm:ml-auto" aria-label="Sort">
            <option value="-created_at">Newest</option>
            <option value="created_at">Oldest</option>
            <option value="-grand_total">Largest</option>
            <option value="-balance_due">Most due</option>
            <option value="due_date">Due soonest</option>
          </Select>
        </div>
        <ErrorBanner error={list.error} className="m-3" />
        {list.isLoading ? (
          <Spinner />
        ) : !list.data?.items.length ? (
          <EmptyState title="No invoices yet" action={<Link href="/invoices/new"><Button variant="primary">Create invoice</Button></Link>} />
        ) : (
          <>
            <Table>
              <thead>
                <tr>
                  <Th>Invoice</Th>
                  <Th className="hidden sm:table-cell">Customer</Th>
                  <Th className="hidden md:table-cell">Date</Th>
                  <Th className="text-right">Total</Th>
                  <Th className="hidden text-right sm:table-cell">Due</Th>
                  <Th>Status</Th>
                </tr>
              </thead>
              <tbody>
                {list.data.items.map((inv) => (
                  <tr key={inv.id} className="cursor-pointer hover:bg-lavender-soft" onClick={() => router.push(`/invoices/${inv.id}`)}>
                    <Td className="whitespace-nowrap">
                      <Link href={`/invoices/${inv.id}`} className="font-medium hover:underline" onClick={(e) => e.stopPropagation()}>
                        {inv.number ?? `Draft #${inv.id}`}
                      </Link>
                      <p className="text-xs text-ink-3 sm:hidden">{inv.customer_name ?? "Walk-in"}</p>
                    </Td>
                    <Td className="hidden text-ink-2 sm:table-cell">{inv.customer_name ?? "Walk-in"}</Td>
                    <Td className="hidden text-ink-2 md:table-cell">{formatDate(inv.invoice_date ?? inv.created_at)}</Td>
                    <Td className="tabular text-right font-medium">{formatINR(inv.grand_total)}</Td>
                    <Td className="tabular hidden text-right sm:table-cell">{inv.status === "draft" ? "—" : formatINR(inv.balance_due)}</Td>
                    <Td>
                      <div className="flex flex-wrap gap-1">
                        <InvoiceStatusBadge status={inv.status} />
                        {inv.status !== "draft" && <PaymentBadge status={inv.payment_status} overdue={inv.is_overdue} />}
                      </div>
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
