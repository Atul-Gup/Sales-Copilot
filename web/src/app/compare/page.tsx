"use client";

import { useEffect, useMemo, useState } from "react";
import {
  ApiError,
  getComparison,
  getEquippedPrice,
  getVariants,
  type EquippedPriceComparison,
  type SpecDiffRow,
  type VariantLabel,
} from "@/lib/api";
import { formatPaise } from "@/lib/format";
import { SourceLink } from "@/components/SourceLink";

function variantLabel(v: VariantLabel): string {
  return `${v.brand} ${v.model} ${v.variant_name}`;
}

export default function ComparePage() {
  const [variants, setVariants] = useState<VariantLabel[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [variantAId, setVariantAId] = useState<number | "">("");
  const [variantBId, setVariantBId] = useState<number | "">("");

  const [rows, setRows] = useState<SpecDiffRow[] | null>(null);
  const [equippedPrice, setEquippedPrice] =
    useState<EquippedPriceComparison | null>(null);
  const [compareError, setCompareError] = useState<string | null>(null);
  const [comparing, setComparing] = useState(false);

  useEffect(() => {
    getVariants()
      .then(setVariants)
      .catch(() =>
        setLoadError("Couldn't load the vehicle list — check the API is running."),
      );
  }, []);

  const canCompare =
    variantAId !== "" && variantBId !== "" && variantAId !== variantBId;

  async function handleCompare() {
    if (!canCompare) return;
    setComparing(true);
    setCompareError(null);
    setRows(null);
    setEquippedPrice(null);
    try {
      const [diffRows, equipped] = await Promise.all([
        getComparison(variantAId as number, variantBId as number),
        // Equipped price is directional (base vs. competitor) — variant A
        // is treated as the base, matching api/services/compare.py.
        getEquippedPrice(variantAId as number, variantBId as number),
      ]);
      setRows(diffRows);
      setEquippedPrice(equipped);
    } catch (err) {
      setCompareError(
        err instanceof ApiError
          ? err.message
          : "Something went wrong running the comparison.",
      );
    } finally {
      setComparing(false);
    }
  }

  const variantOptions = useMemo(() => variants ?? [], [variants]);

  return (
    <div className="mx-auto flex max-w-md flex-col gap-6 px-4 py-8">
      <header>
        <h1 className="text-xl font-semibold">Compare</h1>
        <p className="mt-1 text-sm text-black/60 dark:text-white/60">
          Every figure below carries its source — check it before repeating
          a number to a customer.
        </p>
      </header>

      {loadError && (
        <p className="rounded-lg border border-red-600/30 bg-red-600/10 px-3 py-2 text-sm text-red-700 dark:text-red-400">
          {loadError}
        </p>
      )}

      <div className="flex flex-col gap-3">
        <label className="flex flex-col gap-1 text-sm font-medium">
          Base vehicle
          <select
            className="rounded-lg border border-black/10 bg-transparent px-3 py-2 dark:border-white/10"
            value={variantAId}
            onChange={(e) =>
              setVariantAId(e.target.value ? Number(e.target.value) : "")
            }
          >
            <option value="">Select a vehicle...</option>
            {variantOptions.map((v) => (
              <option key={v.id} value={v.id}>
                {variantLabel(v)}
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1 text-sm font-medium">
          Competitor vehicle
          <select
            className="rounded-lg border border-black/10 bg-transparent px-3 py-2 dark:border-white/10"
            value={variantBId}
            onChange={(e) =>
              setVariantBId(e.target.value ? Number(e.target.value) : "")
            }
          >
            <option value="">Select a vehicle...</option>
            {variantOptions.map((v) => (
              <option key={v.id} value={v.id}>
                {variantLabel(v)}
              </option>
            ))}
          </select>
        </label>

        <button
          type="button"
          onClick={handleCompare}
          disabled={!canCompare || comparing}
          className="rounded-lg bg-blue-600 px-4 py-3 font-medium text-white disabled:opacity-40"
        >
          {comparing ? "Comparing..." : "Compare"}
        </button>
      </div>

      {compareError && (
        <p className="rounded-lg border border-red-600/30 bg-red-600/10 px-3 py-2 text-sm text-red-700 dark:text-red-400">
          {compareError}
        </p>
      )}

      {rows && rows.length === 0 && (
        <p className="text-sm text-black/60 dark:text-white/60">
          No sourced specs found for either vehicle.
        </p>
      )}

      {rows && rows.length > 0 && (
        <section className="flex flex-col gap-3">
          <h2 className="text-lg font-semibold">Spec diff</h2>
          {rows.map((row) => (
            <div
              key={row.attribute}
              className="rounded-lg border border-black/10 p-3 dark:border-white/10"
            >
              <p className="text-sm font-medium">
                {row.attribute.replace(/_/g, " ")}
                {row.unit ? ` (${row.unit})` : ""}
              </p>
              <div className="mt-2 grid grid-cols-2 gap-3">
                <SideValue value={row.variant_a} />
                <SideValue value={row.variant_b} />
              </div>
            </div>
          ))}
        </section>
      )}

      {equippedPrice && (
        <section className="flex flex-col gap-3">
          <h2 className="text-lg font-semibold">Equipped price</h2>
          <div className="rounded-lg border border-black/10 p-3 text-sm dark:border-white/10">
            <p>Base price: {formatPaise(equippedPrice.base_price_paise)}</p>
            <p>
              Competitor base price:{" "}
              {formatPaise(equippedPrice.competitor_base_price_paise)}
            </p>
            <p>
              Cost to match your standard kit:{" "}
              {formatPaise(equippedPrice.added_cost_paise)}
            </p>
            <p className="font-medium">
              Competitor equipped price:{" "}
              {formatPaise(equippedPrice.competitor_equipped_price_paise)}
            </p>
          </div>

          {equippedPrice.included_items.length > 0 && (
            <div className="flex flex-col gap-2">
              <p className="text-sm font-medium">Included to match</p>
              {equippedPrice.included_items.map((item) => (
                <div
                  key={item.feature_key}
                  className="rounded-lg border border-black/10 p-2 text-sm dark:border-white/10"
                >
                  <p>
                    {item.feature_key.replace(/_/g, " ")} —{" "}
                    {formatPaise(item.cost_paise)}
                  </p>
                  <SourceLink source={item.source} />
                </div>
              ))}
            </div>
          )}

          {equippedPrice.unmatchable_items.length > 0 && (
            <div className="flex flex-col gap-2">
              <p className="text-sm font-medium">Can&apos;t be matched</p>
              {equippedPrice.unmatchable_items.map((item) => (
                <div
                  key={item.feature_key}
                  className="rounded-lg border border-amber-600/30 bg-amber-600/10 p-2 text-sm text-amber-800 dark:text-amber-400"
                >
                  {item.feature_key.replace(/_/g, " ")} —{" "}
                  {item.reason === "not_offered"
                    ? "not offered by the competitor"
                    : "optional, but no sourced cost"}
                </div>
              ))}
            </div>
          )}
        </section>
      )}
    </div>
  );
}

function SideValue({ value }: { value: SpecDiffRow["variant_a"] }) {
  if (!value) {
    return <p className="text-sm text-black/40 dark:text-white/40">No data</p>;
  }
  return (
    <div className="flex flex-col gap-1">
      <p className="text-sm">{value.value_text ?? value.value_num}</p>
      <SourceLink source={value.source} />
    </div>
  );
}
