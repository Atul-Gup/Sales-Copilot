"use client";

import { useEffect, useMemo, useState } from "react";
import {
  ApiError,
  getVariants,
  streamObjection,
  type ObjectionResponse,
  type VariantLabel,
} from "@/lib/api";

type FinalResult =
  | { kind: "abstained"; response: ObjectionResponse }
  | { kind: "refused"; violations: string[]; response: ObjectionResponse }
  | { kind: "done"; violations: string[]; response: ObjectionResponse };

function variantLabel(v: VariantLabel): string {
  return `${v.brand} ${v.model} ${v.variant_name}`;
}

export default function ObjectionPage() {
  const [objectionText, setObjectionText] = useState("");
  const [variants, setVariants] = useState<VariantLabel[] | null>(null);
  const [variantAId, setVariantAId] = useState<number | "">("");
  const [variantBId, setVariantBId] = useState<number | "">("");
  const [streaming, setStreaming] = useState(false);
  const [category, setCategory] = useState<string | null>(null);
  const [liveText, setLiveText] = useState("");
  const [final, setFinal] = useState<FinalResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getVariants()
      .then(setVariants)
      .catch(() => setVariants([]));
  }, []);

  const variantOptions = useMemo(() => variants ?? [], [variants]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!objectionText.trim() || streaming) return;

    setStreaming(true);
    setCategory(null);
    setLiveText("");
    setFinal(null);
    setError(null);

    // Spec/safety-comparison objections ("how is the XC60 better than the
    // X3?") can only be grounded against specific variants — retrieval has
    // no way to guess which vehicles free text like "XC60" or "X3" refers
    // to (api/objection/retrieve.py::_spec_comparison_facts reads
    // context.variant_ids directly, not the objection text). Sending the
    // picked variants whenever they're set lets that category actually find
    // facts instead of always refusing for lack of context.
    const variantIds = [variantAId, variantBId].filter(
      (id): id is number => id !== "",
    );
    const context = variantIds.length > 0 ? { variant_ids: variantIds } : {};

    try {
      for await (const event of streamObjection(objectionText, context)) {
        if (event.type === "category") {
          setCategory(event.category);
        } else if (event.type === "token") {
          setLiveText((prev) => prev + event.text);
        } else if (event.type === "abstained") {
          setFinal({ kind: "abstained", response: event.response });
        } else if (event.type === "refused") {
          setFinal({
            kind: "refused",
            violations: event.violations,
            response: event.response,
          });
        } else if (event.type === "done") {
          setFinal({
            kind: "done",
            violations: event.violations,
            response: event.response,
          });
        }
      }
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Something went wrong handling this objection.",
      );
    } finally {
      setStreaming(false);
    }
  }

  return (
    <div className="mx-auto flex max-w-md flex-col gap-6 px-4 py-8">
      <header>
        <h1 className="text-xl font-semibold">Objection</h1>
        <p className="mt-1 text-sm text-black/60 dark:text-white/60">
          Type what the customer said. Every response is checked before it
          finishes streaming — if it can&apos;t be backed up, it&apos;s
          refused instead.
        </p>
      </header>

      <form onSubmit={handleSubmit} className="flex flex-col gap-3">
        <textarea
          className="min-h-24 rounded-lg border border-black/10 bg-transparent px-3 py-2 text-sm dark:border-white/10"
          placeholder="e.g. The X3 holds its value better than the XC60."
          value={objectionText}
          onChange={(e) => setObjectionText(e.target.value)}
        />

        <div className="flex flex-col gap-2">
          <p className="text-xs text-black/50 dark:text-white/50">
            Comparing specific vehicles? Pick them so the answer can be
            grounded in real specs — otherwise a spec comparison has nothing
            to check itself against and gets refused.
          </p>
          <div className="flex gap-2">
            <select
              className="flex-1 rounded-lg border border-black/10 bg-transparent px-3 py-2 text-sm dark:border-white/10"
              value={variantAId}
              onChange={(e) =>
                setVariantAId(e.target.value ? Number(e.target.value) : "")
              }
            >
              <option value="">Our vehicle (optional)</option>
              {variantOptions.map((v) => (
                <option key={v.id} value={v.id}>
                  {variantLabel(v)}
                </option>
              ))}
            </select>
            <select
              className="flex-1 rounded-lg border border-black/10 bg-transparent px-3 py-2 text-sm dark:border-white/10"
              value={variantBId}
              onChange={(e) =>
                setVariantBId(e.target.value ? Number(e.target.value) : "")
              }
            >
              <option value="">Competitor (optional)</option>
              {variantOptions.map((v) => (
                <option key={v.id} value={v.id}>
                  {variantLabel(v)}
                </option>
              ))}
            </select>
          </div>
        </div>

        <button
          type="submit"
          disabled={!objectionText.trim() || streaming}
          className="rounded-lg bg-blue-600 px-4 py-3 font-medium text-white disabled:opacity-40"
        >
          {streaming ? "Thinking..." : "Get a response"}
        </button>
      </form>

      {error && (
        <p className="rounded-lg border border-red-600/30 bg-red-600/10 px-3 py-2 text-sm text-red-700 dark:text-red-400">
          {error}
        </p>
      )}

      {category && (
        <span className="w-fit rounded-full bg-black/5 px-3 py-1 text-xs font-medium text-black/60 dark:bg-white/10 dark:text-white/60">
          {category.replace(/_/g, " ")}
        </span>
      )}

      {streaming && !final && (
        <div className="rounded-lg border border-black/10 p-3 text-sm whitespace-pre-wrap dark:border-white/10">
          {liveText || "Generating..."}
        </div>
      )}

      {final?.kind === "abstained" && (
        <div className="rounded-lg border border-black/10 bg-black/5 p-3 text-sm dark:border-white/10 dark:bg-white/5">
          <p className="font-medium">Not enough to go on</p>
          <p className="mt-1">{final.response.how_to_frame_it}</p>
        </div>
      )}

      {final?.kind === "refused" && (
        <div className="rounded-lg border-2 border-red-600 bg-red-600/10 p-3 text-sm text-red-800 dark:text-red-300">
          <p className="font-semibold">
            Refused — couldn&apos;t verify this response
          </p>
          <p className="mt-1">{final.response.how_to_frame_it}</p>
          {final.violations.length > 0 && (
            <ul className="mt-2 list-inside list-disc">
              {final.violations.map((v) => (
                <li key={v}>{v}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {final?.kind === "done" && (
        <div className="flex flex-col gap-3">
          <Block title="What's true" text={final.response.what_is_true} />
          <Block title="How to frame it" text={final.response.how_to_frame_it} />

          {/* The prominent block — docs/GUARDRAILS.md / docs/PRD.md: "the
              'what not to claim' block must be visually prominent, not a
              footnote." Heavier border, filled background, and a leading
              warning glyph set it apart from the two neutral blocks above,
              deliberately in the strongest visual position on the page. */}
          <div className="rounded-lg border-2 border-amber-500 bg-amber-500/15 p-4">
            <p className="flex items-center gap-2 text-sm font-bold text-amber-900 dark:text-amber-300">
              <span aria-hidden>⚠</span> What NOT to claim
            </p>
            <p className="mt-2 text-sm font-medium text-amber-900 dark:text-amber-200">
              {final.response.what_not_to_claim || "Nothing beyond the above."}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

function Block({ title, text }: { title: string; text: string }) {
  return (
    <div className="rounded-lg border border-black/10 p-3 dark:border-white/10">
      <p className="text-sm font-medium">{title}</p>
      <p className="mt-1 text-sm text-black/80 dark:text-white/80">{text}</p>
    </div>
  );
}
