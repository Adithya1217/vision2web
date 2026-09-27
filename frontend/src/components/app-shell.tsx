"use client";

import clsx from "clsx";
import {
  BarChart3,
  Boxes,
  FileText,
  LayoutDashboard,
  LogOut,
  Menu,
  Package,
  Settings,
  ShoppingCart,
  Sparkles,
  Truck,
  UserCog,
  Users,
  X,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { CommandBar } from "@/components/command-bar";
import { ThemeToggle } from "@/components/theme-toggle";
import { Spinner, Sprite } from "@/components/ui";
import { useAuth } from "@/lib/auth";

export const NAV = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard, perm: "dashboard.view" },
  { href: "/products", label: "Products", icon: Package, perm: "products.read" },
  { href: "/inventory", label: "Stock", icon: Boxes, perm: "inventory.read" },
  { href: "/invoices", label: "Invoices", icon: FileText, perm: "invoices.create" },
  { href: "/customers", label: "Customers & khata", icon: Users, perm: "customers.read" },
  { href: "/suppliers", label: "Suppliers", icon: Truck, perm: "suppliers.read" },
  { href: "/purchase-orders", label: "Purchase orders", icon: ShoppingCart, perm: "suppliers.read" },
  { href: "/reports", label: "Reports", icon: BarChart3, perm: "reports.view" },
  { href: "/staff", label: "Staff", icon: UserCog, perm: "users.manage" },
  { href: "/settings", label: "Shop settings", icon: Settings, perm: "shop.settings" },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const { me, loading, authenticated, can, logout } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const [commandOpen, setCommandOpen] = useState(false);

  useEffect(() => {
    if (!loading && !authenticated) router.replace("/login");
  }, [loading, authenticated, router]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setCommandOpen((o) => !o);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  if (loading || !me) return <Spinner label="Loading your shop" />;

  const items = NAV.filter((n) => can(n.perm));
  const isActive = (href: string) => (href === "/" ? pathname === "/" : pathname.startsWith(href));

  const nav = (
    <nav className="flex flex-1 flex-col gap-1.5 overflow-y-auto p-3" aria-label="Main">
      {items.map(({ href, label, icon: Icon }) => (
        <Link
          key={href}
          href={href}
          onClick={() => setOpen(false)}
          aria-current={isActive(href) ? "page" : undefined}
          className={clsx(
            "flex items-center gap-2.5 rounded-sm border-2 px-2.5 py-1.5 font-mono text-sm font-medium",
            isActive(href)
              ? "border-line-strong bg-butter font-bold text-on-pastel shadow-sm"
              : "border-transparent text-ink-2 hover:bg-lavender-soft hover:text-ink",
          )}
        >
          <Icon className="h-4 w-4" aria-hidden />
          {label}
        </Link>
      ))}
    </nav>
  );

  const brand = (
    <div className="flex items-center gap-2.5 px-4 py-4">
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-sm border-2 border-line-strong bg-butter">
        <Sprite name="crate" size={24} />
      </div>
      <div className="min-w-0">
        <p className="truncate font-pixel text-[10px] leading-4">DUKAAN DESK</p>
        <p className="truncate font-mono text-xs text-ink-3">{me.shop.name}</p>
      </div>
    </div>
  );

  const userBlock = (
    <div className="border-t-[3px] border-line-strong p-3">
      <p className="truncate text-sm font-medium">{me.user.full_name}</p>
      <p className="mb-2 font-mono text-xs capitalize text-ink-3">{me.user.role}</p>
      <button onClick={logout} className="flex items-center gap-1.5 font-mono text-xs text-ink-2 hover:text-ink">
        <LogOut className="h-3.5 w-3.5" /> Sign out
      </button>
    </div>
  );

  return (
    <div className="min-h-screen lg:flex">
      <aside className="no-print sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r-[3px] border-line-strong bg-surface lg:flex">
        {brand}
        {nav}
        {userBlock}
      </aside>

      {open && (
        <div className="no-print fixed inset-0 z-40 lg:hidden" onClick={() => setOpen(false)}>
          <div className="absolute inset-0 bg-[var(--overlay)]" />
          <aside
            className="absolute left-0 top-0 flex h-full w-64 flex-col border-r-[3px] border-line-strong bg-surface"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between pr-2">
              {brand}
              <button className="rounded p-2 text-ink-2" onClick={() => setOpen(false)} aria-label="Close menu">
                <X className="h-5 w-5" />
              </button>
            </div>
            {nav}
            {userBlock}
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="no-print sticky top-0 z-30 flex h-14 items-center gap-2 border-b-[3px] border-line-strong bg-surface px-4">
          <button className="rounded-lg p-2 text-ink-2 lg:hidden" onClick={() => setOpen(true)} aria-label="Open menu">
            <Menu className="h-5 w-5" />
          </button>
          {can("ai.use") && (
            <button
              onClick={() => setCommandOpen(true)}
              className="flex h-9 min-w-0 flex-1 items-center gap-2 rounded-sm border-2 border-line-strong bg-surface-2 px-3 text-left text-sm text-ink-3 hover:bg-lavender-soft hover:text-ink-2 sm:max-w-md"
            >
              <Sparkles className="h-4 w-4 shrink-0 text-info" aria-hidden />
              <span className="truncate">Ask or command… “bill 2 soap for Ramesh”</span>
              <kbd className="ml-auto hidden rounded-sm border-2 border-line-strong px-1.5 font-mono text-[10px] sm:inline">Ctrl K</kbd>
            </button>
          )}
          <div className="ml-auto flex items-center gap-1">
            <ThemeToggle />
          </div>
        </header>
        <main className="print-full mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-8 sm:py-8">{children}</main>
      </div>
      <CommandBar open={commandOpen} onClose={() => setCommandOpen(false)} />
    </div>
  );
}
