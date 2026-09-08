"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, postChat, type ChatResponse } from "@/lib/api";

type Message =
  | { id: string; role: "user"; text: string }
  | { id: string; role: "assistant"; response: ChatResponse }
  | { id: string; role: "error"; text: string };

function newId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

// A refusal renders as its own shape, not a dead end (T7.3 groundwork): a
// distinct border/label rather than the same bubble style as an answered
// response, so a consultant never mistakes "nothing retrieved" for silence.
function AssistantBubble({ response }: { response: ChatResponse }) {
  if (response.refused) {
    return (
      <div className="max-w-[85%] rounded-2xl rounded-bl-sm border border-amber-600/30 bg-amber-600/10 px-4 py-3 text-sm text-amber-900 dark:text-amber-300">
        <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-amber-700 dark:text-amber-400">
          Not in the sourced documents
        </p>
        <p>{response.text}</p>
      </div>
    );
  }

  return (
    <div className="max-w-[85%] rounded-2xl rounded-bl-sm border border-black/10 bg-black/[0.03] px-4 py-3 text-sm dark:border-white/10 dark:bg-white/[0.04]">
      {response.conceded && (
        <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-blue-700 dark:text-blue-400">
          Honest concession
        </p>
      )}
      <p className="whitespace-pre-wrap">{response.text}</p>
      {response.citations.length > 0 && (
        <div className="mt-3 space-y-1 border-t border-black/10 pt-2 dark:border-white/10">
          {response.citations.map((c) => (
            <p
              key={c.marker}
              className="text-xs text-black/50 dark:text-white/50"
            >
              [{c.marker}]{c.section ? ` ${c.section} — ` : " "}
              {c.text}
            </p>
          ))}
        </div>
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
