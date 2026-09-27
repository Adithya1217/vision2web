"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { AuthFrame } from "@/components/auth-frame";
import { Button, ErrorBanner, Field, Input, Select } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { STATES } from "@/lib/format";

export default function RegisterPage() {
  const { acceptToken } = useAuth();
  const router = useRouter();
  const [form, setForm] = useState({ shop: "", state: "29", gstin: "", owner: "", email: "", password: "" });
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await api.post<{ access_token: string }>("/auth/register", {
        shop: {
          name: form.shop,
          state_code: form.state,
          gstin: form.gstin.trim().toUpperCase() || null,
          timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Kolkata",
        },
        owner_name: form.owner,
        email: form.email,
        password: form.password,
      });
      acceptToken(res.access_token);
      router.replace("/");
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthFrame title="Create your shop" subtitle="You'll be the owner. Add staff after signing in.">
      <form onSubmit={submit} className="flex flex-col gap-3">
        <ErrorBanner error={error} />
        <Field label="Shop name">{(id) => <Input id={id} required value={form.shop} onChange={set("shop")} />}</Field>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label="State (for GST)">
            {(id) => (
              <Select id={id} value={form.state} onChange={set("state")}>
                {STATES.map(([code, name]) => (
                  <option key={code} value={code}>
                    {code} · {name}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field label="GSTIN (optional)">{(id) => <Input id={id} value={form.gstin} onChange={set("gstin")} maxLength={15} />}</Field>
        </div>
        <Field label="Your name">{(id) => <Input id={id} required value={form.owner} onChange={set("owner")} />}</Field>
        <Field label="Email">{(id) => <Input id={id} type="email" required value={form.email} onChange={set("email")} />}</Field>
        <Field label="Password" hint="At least 8 characters">
          {(id) => <Input id={id} type="password" minLength={8} required value={form.password} onChange={set("password")} />}
        </Field>
        <Button type="submit" variant="primary" loading={busy} className="mt-1">
          Create shop
        </Button>
        <p className="text-center text-sm text-ink-3">
          Already registered?{" "}
          <Link href="/login" className="font-medium text-accent hover:underline">
            Sign in
          </Link>
        </p>
      </form>
    </AuthFrame>
  );
}
