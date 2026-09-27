"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { useToast } from "@/components/toast";
import { Button, ErrorBanner, Field, Input, Modal, Select, Textarea } from "@/components/ui";
import { api } from "@/lib/api";
import { useSubmitter } from "@/lib/hooks";
import { isMoney } from "@/lib/money";
import type { Category, Page, Product } from "@/lib/types";

const GST_RATES = ["0", "0.25", "3", "5", "12", "18", "28", "40"];

export function ProductFormModal({ product, open, onClose }: { product?: Product; open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const submitter = useSubmitter();
  const cats = useQuery({ queryKey: ["categories"], queryFn: () => api.get<Page<Category>>("/categories", { page_size: 200 }) });
  const [f, setF] = useState(() => ({
    name: product?.name ?? "",
    sku: product?.sku ?? "",
    category_id: product?.category_id ? String(product.category_id) : "",
    hsn_code: product?.hsn_code ?? "",
    unit: product?.unit ?? "pcs",
    sale_price: product?.sale_price ?? "",
    cost_price: product?.cost_price ?? "",
    gst_rate: product ? String(Number(product.gst_rate)) : "18",
    opening_quantity: "0",
    low_stock_threshold: String(product?.low_stock_threshold ?? 5),
    reorder_quantity: String(product?.reorder_quantity ?? 0),
  }));
  const [newCat, setNewCat] = useState("");
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setF((x) => ({ ...x, [k]: e.target.value }));

  const priceError = f.sale_price && !isMoney(f.sale_price) ? "Use a number with up to 2 decimals" : undefined;
  const costError = f.cost_price && !isMoney(f.cost_price) ? "Use a number with up to 2 decimals" : undefined;

  const save = useMutation({
    mutationFn: async () => {
      let categoryId = f.category_id ? Number(f.category_id) : null;
      if (newCat.trim()) {
        const cat = await api.post<Category>("/categories", { name: newCat.trim() });
        categoryId = cat.id;
      }
      const body: Record<string, unknown> = {
        name: f.name,
        sku: f.sku,
        category_id: categoryId,
        hsn_code: f.hsn_code || null,
        unit: f.unit || "pcs",
        sale_price: f.sale_price,
        cost_price: f.cost_price || null,
        gst_rate: f.gst_rate,
        low_stock_threshold: Number(f.low_stock_threshold || 0),
        reorder_quantity: Number(f.reorder_quantity || 0),
      };
      if (product) return api.patch<Product>(`/products/${product.id}`, body, submitter.keyFor(body));
      body.opening_quantity = Number(f.opening_quantity || 0);
      return api.post<Product>("/products", body, submitter.keyFor(body));
    },
    onSuccess: (p) => {
      submitter.done();
      qc.invalidateQueries({ queryKey: ["products"] });
      qc.invalidateQueries({ queryKey: ["categories"] });
      toast(product ? `Saved ${p.name}` : `Added ${p.name}`);
      onClose();
    },
  });

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={product ? `Edit ${product.name}` : "Add product"}
      wide
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            loading={save.isPending}
            disabled={!f.name || !f.sku || !f.sale_price || !!priceError || !!costError}
            onClick={() => save.mutate()}
          >
            {product ? "Save changes" : "Add product"}
          </Button>
        </>
      }
    >
      <ErrorBanner error={save.error} className="mb-3" />
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="Name">{(id) => <Input id={id} value={f.name} onChange={set("name")} required />}</Field>
        <Field label="SKU" hint="Unique within your shop">
          {(id) => <Input id={id} value={f.sku} onChange={set("sku")} required />}
        </Field>
        <Field label="Category">
          {(id) => (
            <Select id={id} value={f.category_id} onChange={set("category_id")} disabled={!!newCat}>
              <option value="">No category</option>
              {cats.data?.items.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="…or new category">{(id) => <Input id={id} value={newCat} onChange={(e) => setNewCat(e.target.value)} />}</Field>
        <Field label="Sale price (₹, excl. GST)" error={priceError}>
          {(id) => <Input id={id} inputMode="decimal" value={f.sale_price} onChange={set("sale_price")} required />}
        </Field>
        <Field label="Cost price (₹, optional)" error={costError} hint="Used for valuation and profit; never estimated">
          {(id) => <Input id={id} inputMode="decimal" value={f.cost_price} onChange={set("cost_price")} />}
        </Field>
        <Field label="GST rate">
          {(id) => (
            <Select id={id} value={f.gst_rate} onChange={set("gst_rate")}>
              {GST_RATES.map((r) => (
                <option key={r} value={r}>
                  {r}%
                </option>
              ))}
            </Select>
          )}
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="HSN code">{(id) => <Input id={id} value={f.hsn_code} onChange={set("hsn_code")} />}</Field>
          <Field label="Unit">{(id) => <Input id={id} value={f.unit} onChange={set("unit")} />}</Field>
        </div>
        {!product && (
          <Field label="Opening stock" hint="Recorded as an opening-balance movement">
            {(id) => <Input id={id} type="number" min={0} value={f.opening_quantity} onChange={set("opening_quantity")} />}
          </Field>
        )}
        <div className="grid grid-cols-2 gap-3">
          <Field label="Low-stock alert at">
            {(id) => <Input id={id} type="number" min={0} value={f.low_stock_threshold} onChange={set("low_stock_threshold")} />}
          </Field>
          <Field label="Reorder qty">
            {(id) => <Input id={id} type="number" min={0} value={f.reorder_quantity} onChange={set("reorder_quantity")} />}
          </Field>
        </div>
      </div>
      {product && (
        <p className="mt-3 text-xs text-ink-3">
          Stock quantity can&apos;t be edited here. Use <strong>Adjust stock</strong> so every change is recorded.
        </p>
      )}
    </Modal>
  );
}

const ADJUST_TYPES = [
  { value: "manual_increase", label: "Add stock" },
  { value: "manual_decrease", label: "Remove stock" },
  { value: "damage", label: "Damaged / expired" },
  { value: "correction", label: "Correct to physical count" },
] as const;

export function StockAdjustModal({ product, open, onClose }: { product: Product | null; open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const submitter = useSubmitter();
  const [type, setType] = useState<(typeof ADJUST_TYPES)[number]["value"]>("manual_increase");
  const [qty, setQty] = useState("");
  const [reason, setReason] = useState("");

  const n = Number(qty);
  const valid = Number.isInteger(n) && (type === "correction" ? n >= 0 : n > 0) && reason.trim().length >= 3;
  const next = product
    ? type === "correction"
      ? n
      : type === "manual_increase"
        ? product.quantity + n
        : product.quantity - n
    : 0;

  const save = useMutation({
    mutationFn: () => {
      const body =
        type === "correction"
          ? { product_id: product!.id, movement_type: type, counted_quantity: n, reason }
          : { product_id: product!.id, movement_type: type, quantity: n, reason };
      return api.post("/inventory/adjustments", body, submitter.keyFor(body));
    },
    onSuccess: () => {
      submitter.done();
      qc.invalidateQueries({ queryKey: ["products"] });
      qc.invalidateQueries({ queryKey: ["movements"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      toast(`Stock updated for ${product?.name}`);
      setQty("");
      setReason("");
      onClose();
    },
  });

  if (!product) return null;
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Adjust stock · ${product.name}`}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" disabled={!valid || next < 0} loading={save.isPending} onClick={() => save.mutate()}>
            Record adjustment
          </Button>
        </>
      }
    >
      <ErrorBanner error={save.error} className="mb-3" />
      <div className="flex flex-col gap-3">
        <Field label="Type">
          {(id) => (
            <Select id={id} value={type} onChange={(e) => setType(e.target.value as typeof type)}>
              {ADJUST_TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label={type === "correction" ? "Counted quantity" : "Quantity"}>
          {(id) => <Input id={id} type="number" min={0} value={qty} onChange={(e) => setQty(e.target.value)} />}
        </Field>
        <Field label="Reason" hint="Required. Saved permanently with the movement.">
          {(id) => <Textarea id={id} value={reason} onChange={(e) => setReason(e.target.value)} />}
        </Field>
        <p className="tabular text-sm">
          Current <strong>{product.quantity}</strong> → after{" "}
          <strong className={next < 0 ? "text-critical-ink" : ""}>{qty === "" ? "—" : next}</strong>
          {next < 0 && <span className="ml-2 text-xs text-critical-ink">Stock can&apos;t go below zero</span>}
        </p>
      </div>
    </Modal>
  );
}
