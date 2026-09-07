"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

// Bottom tab bar, not a top nav — docs/PRD.md: the primary user is "on the
// showroom floor, on their phone, mid-conversation." A bottom bar keeps
// every destination inside one-handed thumb reach; a top nav on a tall
// phone screen does not.
const TABS = [
  { href: "/", label: "Home" },
  { href: "/compare", label: "Compare" },
  { href: "/objection", label: "Objection" },
] as const;

export function BottomNav() {
  const pathname = usePathname();

  return (
    <nav
      className="fixed inset-x-0 bottom-0 z-10 flex border-t border-black/10 bg-[var(--background)] pb-[env(safe-area-inset-bottom)] dark:border-white/10"
      aria-label="Primary"
    >
      {TABS.map((tab) => {
        const active =
          tab.href === "/" ? pathname === "/" : pathname.startsWith(tab.href);
        return (
          <Link
            key={tab.href}
            href={tab.href}
            className={`flex-1 px-2 py-3 text-center text-sm font-medium ${
              active
                ? "text-blue-600 dark:text-blue-400"
                : "text-black/60 dark:text-white/60"
            }`}
            aria-current={active ? "page" : undefined}
          >
            {tab.label}
          </Link>
        );
      })}
    </nav>
  );
}
