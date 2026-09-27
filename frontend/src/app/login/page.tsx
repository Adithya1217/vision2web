"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { AuthFrame } from "@/components/auth-frame";
import { Button, ErrorBanner, Field, Input } from "@/components/ui";
import { useAuth } from "@/lib/auth";

export default function LoginPage() {
  const { login, authenticated } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (authenticated) router.replace("/");
  }, [authenticated, router]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
      router.replace("/");
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthFrame title="Sign in" subtitle="Welcome back to your shop.">
      <form onSubmit={submit} className="flex flex-col gap-3">
        <ErrorBanner error={error} />
        <Field label="Email">
          {(id) => <Input id={id} type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />}
        </Field>
        <Field label="Password">
          {(id) => (
            <Input id={id} type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
          )}
        </Field>
        <Button type="submit" variant="primary" loading={busy} className="mt-1">
          Sign in
        </Button>
        <p className="text-center text-sm text-ink-3">
          New business?{" "}
          <Link href="/register" className="font-medium text-info hover:underline">
            Create a shop
          </Link>
        </p>
      </form>
    </AuthFrame>
  );
}
