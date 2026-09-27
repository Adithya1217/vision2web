"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, ArchiveRestore, Pencil, Plus, SlidersHorizontal } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { StockBadge } from "@/components/badges";
import { ProductFormModal, StockAdjustModal } from "@/components/product-forms";
import { useToast } from "@/components/toast";
import {
  Button,
  Card,
  EmptyState,
  ErrorBanner,
  PageHeader,
  Pagination,
  SearchInput,
  Select,
  Spinner,
  Table,
  Td,
  Th,
} from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useDebounced } from "@/lib/hooks";
import { formatINR } from "@/lib/money";
import type { Category, Page, Product } from "@/lib/types";

export default function ProductsPage() {
  return (
    <Suspense fallback={<Spinner />}>
      <ProductsPageInner />
    </Suspense>
  );
}

function ProductsPageInner() {
  const initial = useSearchParams().get("stock") ?? "";
  const { can } = useAuth();
  const toast = useToast();
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("active");
  const [stock, setStock] = useState(initial);
  const [category, setCategory] = useState("");
  const [sort, setSort] = useState("name");
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState<Product | undefined>();
  const [formOpen, setFormOpen] = useState(false);
  const [adjusting, setAdjusting] = useState<Product | null>(null);
  const search = useDebounced(q);

  const params = { q: search, status, stock_status: stock, category_id: category, sort, page, page_size: 25 };
  const list = useQuery({ queryKey: ["products", params], queryFn: () => api.get<Page<Product>>("/products", params) });
  const cats = useQuery({ queryKey: ["categories"], queryFn: () => api.get<Page<Category>>("/categories", { page_size: 200 }) });

  const toggle = useMutation({
    mutationFn: (p: Product) => api.post<Product>(`/products/${p.id}/${p.is_active ? "archive" : "restore"}`),
    onSuccess: (p) => {
      qc.invalidateQueries({ queryKey: ["products"] });
      toast(p.is_active ? `Restored ${p.name}` : `Archived ${p.name}`);
    },
    onError: (e) => toast(e instanceof Error ? e.message : "Failed", "error"),
  });

  const reset = (fn: (v: string) => void) => (e: React.ChangeEvent<HTMLSelectElement>) => {
    fn(e.target.value);
    setPage(1);
  };

  return (
    <>
      <PageHeader
        title="Products"
        subtitle="Catalogue, prices and GST rates. Stock changes are always recorded as movements."
        actions={
          can("products.write") && (
            <Button
              variant="primary"
              onClick={() => {
                setEditing(undefined);
                setFormOpen(true);
              }}
            >
              <Plus className="h-4 w-4" /> Add product
            </Button>
          )
        }
      />
      <Card>
        <div className="flex flex-wrap items-center gap-2 border-b border-line p-3">
          <SearchInput
            value={q}
            onChange={(v) => {
              setQ(v);
              setPage(1);
            }}
            placeholder="Search name or SKU"
          />
          <Select value={category} onChange={reset(setCategory)} className="w-auto" aria-label="Category">
            <option value="">All categories</option>
            {cats.data?.items.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </Select>
          <Select value={stock} onChange={reset(setStock)} className="w-auto" aria-label="Stock level">
            <option value="">Any stock level</option>
            <option value="healthy">Healthy</option>
            <option value="low">Low stock</option>
            <option value="out">Out of stock</option>
          </Select>
          <Select value={status} onChange={reset(setStatus)} className="w-auto" aria-label="Status">
            <option value="active">Active</option>
            <option value="archived">Archived</option>
            <option value="all">All</option>
          </Select>
          <Select value={sort} onChange={reset(setSort)} className="w-auto sm:ml-auto" aria-label="Sort">
            <option value="name">Name A–Z</option>
            <option value="-name">Name Z–A</option>
            <option value="quantity">Stock: low first</option>
            <option value="-quantity">Stock: high first</option>
            <option value="-sale_price">Price: high first</option>
            <option value="-updated_at">Recently updated</option>
          </Select>
        </div>
        <ErrorBanner error={list.error} className="m-3" />
        {list.isLoading ? (
          <Spinner />
        ) : !list.data?.items.length ? (
          <EmptyState title="No products found" hint="Adjust the filters or add your first product." />
        ) : (
          <>
            <Table>
              <thead>
                <tr>
                  <Th>Product</Th>
                  <Th className="hidden md:table-cell">Category</Th>
                  <Th className="text-right">Price</Th>
                  <Th className="hidden text-right sm:table-cell">GST</Th>
                  <Th className="text-right">Stock</Th>
                  <Th className="hidden sm:table-cell">Status</Th>
                  <Th className="text-right">
                    <span className="sr-only">Actions</span>
                  </Th>
                </tr>
              </thead>
              <tbody>
                {list.data.items.map((p) => (
                  <tr key={p.id} className={p.is_active ? "" : "opacity-60"}>
                    <Td>
                      <p className="font-medium">{p.name}</p>
                      <p className="text-xs text-ink-3">{p.sku}</p>
                    </Td>
                    <Td className="hidden text-ink-2 md:table-cell">{p.category?.name ?? "—"}</Td>
                    <Td className="tabular text-right">{formatINR(p.sale_price)}</Td>
                    <Td className="tabular hidden text-right text-ink-2 sm:table-cell">{Number(p.gst_rate)}%</Td>
                    <Td className="tabular text-right font-medium">
                      {p.quantity} <span className="text-xs font-normal text-ink-3">{p.unit}</span>
                    </Td>
                    <Td className="hidden sm:table-cell">
                      <StockBadge status={p.stock_status} />
                    </Td>
                    <Td className="text-right">
                      <div className="flex justify-end gap-1">
                        {can("inventory.adjust") && p.is_active && (
                          <Button size="sm" variant="ghost" onClick={() => setAdjusting(p)} aria-label={`Adjust stock of ${p.name}`}>
                            <SlidersHorizontal className="h-4 w-4" />
                          </Button>
                        )}
                        {can("products.write") && (
                          <>
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => {
                                setEditing(p);
                                setFormOpen(true);
                              }}
                              aria-label={`Edit ${p.name}`}
                            >
                              <Pencil className="h-4 w-4" />
                            </Button>
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => toggle.mutate(p)}
                              aria-label={p.is_active ? `Archive ${p.name}` : `Restore ${p.name}`}
                            >
                              {p.is_active ? <Archive className="h-4 w-4" /> : <ArchiveRestore className="h-4 w-4" />}
                            </Button>
                          </>
                        )}
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
      {formOpen && <ProductFormModal key={editing?.id ?? "new"} product={editing} open onClose={() => setFormOpen(false)} />}
      <StockAdjustModal product={adjusting} open={!!adjusting} onClose={() => setAdjusting(null)} />
    </>
  );
}
