"use client";

import { useEffect, useState } from "react";
import { getHealth } from "@/lib/api";

type ApiState = "checking" | "ok" | "down";

export default function HomePage() {
  const [apiState, setApiState] = useState<ApiState>("checking");

  useEffect(() => {
    let cancelled = false;
    getHealth()
      .then(() => {
        if (!cancelled) setApiState("ok");
      })
      .catch(() => {
        if (!cancelled) setApiState("down");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="mx-auto flex max-w-md flex-col gap-6 px-4 py-8">
      <header>
        <h1 className="text-2xl font-semibold">Showroom Copilot</h1>
        <p className="mt-1 text-sm text-black/60 dark:text-white/60">
          Grounded comparisons and honest objection handling, built for the
          showroom floor.
        </p>
      </header>

      <div
        className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-sm ${
          apiState === "ok"
            ? "border-green-600/30 bg-green-600/10 text-green-700 dark:text-green-400"
            : apiState === "down"
              ? "border-red-600/30 bg-red-600/10 text-red-700 dark:text-red-400"
              : "border-black/10 bg-black/5 text-black/60 dark:border-white/10 dark:bg-white/5 dark:text-white/60"
        }`}
        role="status"
      >
        <span
          className={`h-2 w-2 shrink-0 rounded-full ${
            apiState === "ok"
              ? "bg-green-600"
              : apiState === "down"
                ? "bg-red-600"
                : "bg-black/30 dark:bg-white/30"
          }`}
          aria-hidden
        />
        {apiState === "checking" && "Checking connection to the API..."}
        {apiState === "ok" && "Connected to the API."}
        {apiState === "down" &&
          "Can't reach the API — check NEXT_PUBLIC_API_BASE_URL and that it's running."}
      </div>

      <nav className="grid gap-3">
        <a
          href="/compare"
          className="rounded-lg border border-black/10 px-4 py-3 font-medium dark:border-white/10"
        >
          Compare two models →
        </a>
        <a
          href="/objection"
          className="rounded-lg border border-black/10 px-4 py-3 font-medium dark:border-white/10"
        >
          Handle an objection →
        </a>
      </nav>
    </div>
  );
}
