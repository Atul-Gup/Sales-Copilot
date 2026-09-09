"use client";

import { useEffect, useRef, useState } from "react";
import {
  ApiError,
  postChat,
  type ChatResponse,
  type Claim,
  type Warning,
} from "@/lib/api";

type Message =
  | { id: string; role: "user"; text: string }
  | { id: string; role: "assistant"; response: ChatResponse }
  | { id: string; role: "error"; text: string };

function newId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

// One small numbered inline marker per cited claim (T7.7). Numbered
// sequentially by position in `response`, not by the backend's internal
// chunk-offer order (that number isn't part of the public API shape) —
// see `renderResponseWithCitations` below for how a marker is matched back
// to its `Claim`.
function CitationChip({
  number,
  active,
  onClick,
}: {
  number: number;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-expanded={active}
      aria-label={`Show source ${number}`}
      className={`mx-0.5 inline-flex h-4 min-w-4 -translate-y-0.5 items-center justify-center rounded-full px-1 align-middle text-[10px] font-semibold leading-none transition-colors ${
        active
          ? "bg-blue-600 text-white"
          : "bg-black/10 text-black/60 hover:bg-blue-600/20 dark:bg-white/15 dark:text-white/70"
      }`}
    >
      {number}
    </button>
  );
}

// Splits `text` on its `[n]` markers and renders each as a `CitationChip`
// instead of raw bracket text — those markers are for verification, not
// something a consultant reads aloud (api/services/generate.py's prompt
// rules), so they're never shown as literal "[1]" in the UI. Matches each
// marker occurrence to `claims[i]` *by position*, not by the number inside
// the brackets: `extract_claims` (backend) walks the response text in the
// same left-to-right order, one `Claim` per marker occurrence, so the Nth
// marker in the text is always `claims[N]` — this is exactly what lets the
// frontend do this without the API needing to expose the internal marker
// number at all.
function renderResponseWithCitations(
  text: string,
  claims: Claim[],
  expandedIndex: number | null,
  onToggle: (index: number) => void,
) {
  const parts = text.split(/(\[\d+\])/g);
  let claimIndex = 0;
  return parts.map((part, i) => {
    if (!/^\[\d+\]$/.test(part)) {
      return <span key={i}>{part}</span>;
    }
    const index = claimIndex;
    claimIndex += 1;
    const claim = claims[index];
    if (!claim) return null; // no matching claim — nothing to show a source for
    return (
      <CitationChip
        key={i}
        number={index + 1}
        active={expandedIndex === index}
        onClick={() => onToggle(index)}
      />
    );
  });
}

// A source panel for one expanded claim — document + section, and the
// exact sentence it grounds. Toggled via React state (`expandedIndex`) in
// AssistantBubble, not direct DOM manipulation.
function SourcePanel({ claim }: { claim: Claim }) {
  return (
    <div className="mt-2 rounded-lg border border-black/10 bg-black/[0.02] px-3 py-2 text-xs dark:border-white/10 dark:bg-white/[0.03]">
      <p className="font-semibold text-black/70 dark:text-white/70">{claim.source}</p>
      <p className="mt-0.5 text-black/50 dark:text-white/50">&ldquo;{claim.text_span}&rdquo;</p>
    </div>
  );
}

const WARNING_STYLES: Record<string, { label: string; classes: string }> = {
  must_concede: {
    label: "Honest concession",
    classes:
      "border-blue-600/30 bg-blue-600/10 text-blue-900 dark:text-blue-300 [&>p:first-child]:text-blue-700 dark:[&>p:first-child]:text-blue-400",
  },
  no_answer_outside_corpus: {
    label: "Not in the sourced documents",
    classes:
      "border-amber-600/30 bg-amber-600/10 text-amber-900 dark:text-amber-300 [&>p:first-child]:text-amber-700 dark:[&>p:first-child]:text-amber-400",
  },
  disparagement: {
    label: "Guardrail flag",
    classes:
      "border-red-600/30 bg-red-600/10 text-red-900 dark:text-red-300 [&>p:first-child]:text-red-700 dark:[&>p:first-child]:text-red-400",
  },
};

// A visually distinct callout per warning — never blended into the answer
// paragraph (T7.7). Renders nothing when `warnings` is empty.
function GuardrailWarning({ warnings }: { warnings: Warning[] }) {
  if (warnings.length === 0) return null;
  return (
    <div className="mb-2 space-y-1.5">
      {warnings.map((warning, i) => {
        const style = WARNING_STYLES[warning.type] ?? {
          label: warning.type,
          classes: "border-black/15 bg-black/[0.04] dark:border-white/15 dark:bg-white/[0.05]",
        };
        return (
          <div key={i} className={`rounded-xl border px-3 py-2 text-sm ${style.classes}`}>
            <p className="text-xs font-semibold uppercase tracking-wide">{style.label}</p>
            <p>{warning.text}</p>
          </div>
        );
      })}
    </div>
  );
}

// A refusal/concession renders its own callout via GuardrailWarning rather
// than a distinct bubble shape (T7.3 groundwork) — derived from `warnings`
// containing a "no_answer_outside_corpus"/"must_concede" entry, since the
// old boolean `refused`/`conceded` fields no longer exist on the response.
function AssistantBubble({ response }: { response: ChatResponse }) {
  const [expandedIndex, setExpandedIndex] = useState<number | null>(null);
  const isRefusal = response.warnings.some((w) => w.type === "no_answer_outside_corpus");

  return (
    <div
      className={`max-w-[85%] rounded-2xl rounded-bl-sm border px-4 py-3 text-sm ${
        isRefusal
          ? "border-amber-600/30 bg-amber-600/10 text-amber-900 dark:text-amber-300"
          : "border-black/10 bg-black/[0.03] dark:border-white/10 dark:bg-white/[0.04]"
      }`}
    >
      <GuardrailWarning warnings={response.warnings} />
      <p className="whitespace-pre-wrap">
        {renderResponseWithCitations(
          response.response,
          response.claims,
          expandedIndex,
          (index) => setExpandedIndex((current) => (current === index ? null : index)),
        )}
      </p>
      {expandedIndex !== null && response.claims[expandedIndex] && (
        <SourcePanel claim={response.claims[expandedIndex]} />
      )}
    </div>
  );
}

export default function HomePage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const query = input.trim();
    if (!query || sending) return;

    setMessages((prev) => [...prev, { id: newId(), role: "user", text: query }]);
    setInput("");
    setSending(true);

    try {
      const response = await postChat(query);
      setMessages((prev) => [
        ...prev,
        { id: newId(), role: "assistant", response },
      ]);
    } catch (err) {
      const text =
        err instanceof ApiError
          ? `Couldn't reach the copilot (${err.status}): ${err.message}`
          : "Couldn't reach the copilot — check your connection and try again.";
      setMessages((prev) => [...prev, { id: newId(), role: "error", text }]);
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="mx-auto flex h-full w-full max-w-2xl flex-col px-4">
      <header className="border-b border-black/10 py-4 dark:border-white/10">
        <h1 className="text-lg font-semibold">Showroom Copilot</h1>
        <p className="text-xs text-black/60 dark:text-white/60">
          Ask about specs, comparisons, or objections — one box, one answer.
        </p>
      </header>

      <div className="flex-1 space-y-4 overflow-y-auto py-4">
        {messages.length === 0 && (
          <p className="mt-8 text-center text-sm text-black/40 dark:text-white/40">
            Try: &ldquo;How does the XC60&apos;s wheelbase compare to the X3&apos;s?&rdquo;
          </p>
        )}
        {messages.map((message) => {
          if (message.role === "user") {
            return (
              <div key={message.id} className="flex justify-end">
                <div className="max-w-[85%] rounded-2xl rounded-br-sm bg-blue-600 px-4 py-3 text-sm text-white">
                  {message.text}
                </div>
              </div>
            );
          }
          if (message.role === "error") {
            return (
              <div key={message.id} className="flex justify-start">
                <div className="max-w-[85%] rounded-2xl rounded-bl-sm border border-red-600/30 bg-red-600/10 px-4 py-3 text-sm text-red-700 dark:text-red-400">
                  {message.text}
                </div>
              </div>
            );
          }
          return (
            <div key={message.id} className="flex justify-start">
              <AssistantBubble response={message.response} />
            </div>
          );
        })}
        {sending && (
          <div className="flex justify-start">
            <div className="rounded-2xl rounded-bl-sm border border-black/10 bg-black/[0.03] px-4 py-3 text-sm text-black/50 dark:border-white/10 dark:bg-white/[0.04] dark:text-white/50">
              Thinking…
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <form
        onSubmit={handleSubmit}
        className="flex gap-2 border-t border-black/10 py-3 dark:border-white/10"
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask about a spec, comparison, or objection…"
          className="flex-1 rounded-full border border-black/15 bg-transparent px-4 py-2 text-sm outline-none focus:border-blue-600 dark:border-white/15"
          disabled={sending}
        />
        <button
          type="submit"
          disabled={sending || !input.trim()}
          className="rounded-full bg-blue-600 px-5 py-2 text-sm font-medium text-white disabled:opacity-40"
        >
          Send
        </button>
      </form>
    </div>
  );
}
