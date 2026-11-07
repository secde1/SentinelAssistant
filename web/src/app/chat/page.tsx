"use client";

import { useEffect, useRef, useState } from "react";
import { IconLock, IconSend } from "@/components/icons";
import { Button, Card, ErrorBox, Notice, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import { timeOnly } from "@/lib/format";
import { useApi, usePageTitle } from "@/lib/hooks";

interface Msg { role: "user" | "assistant"; content: string; ts: string; error?: boolean }
interface ChatStatus { enabled: boolean; available: boolean; auth?: string; blocked?: string | null; model?: string }

const SUGGESTIONS = [
  "Which disks on this computer are running low on space?",
  "Summarize today's SENTINAL AI activity.",
  "How many computers in AD still run Windows 10?",
  "Which departments have the most inactive computers?",
];
const STORE = "sentinal-chat-v1";

export default function ChatPage() {
  usePageTitle("AI Chat");
  const status = useApi<ChatStatus>("/api/chat/status");
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    try {
      const saved = sessionStorage.getItem(STORE);
      if (saved) setMessages(JSON.parse(saved));
    } catch { /* brauzer xotirasi yo'q — suhbat faqat sahifada */ }
  }, []);

  useEffect(() => {
    try { sessionStorage.setItem(STORE, JSON.stringify(messages.slice(-40))); } catch { /* ignore */ }
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  async function send(text: string) {
    const content = text.trim();
    if (!content || busy) return;
    const next: Msg[] = [...messages, { role: "user", content, ts: new Date().toISOString() }];
    setMessages(next);
    setInput("");
    setBusy(true);
    try {
      const history = next.filter((m) => !m.error).map(({ role, content }) => ({ role, content }));
      const r = await api.post<{ reply?: string; error?: string }>("/api/chat", { messages: history });
      setMessages((cur) => [...cur, r.reply
        ? { role: "assistant", content: r.reply, ts: new Date().toISOString() }
        : { role: "assistant", content: r.error || "No reply.", ts: new Date().toISOString(), error: true }]);
    } catch (e) {
      setMessages((cur) => [...cur, { role: "assistant", content: e instanceof Error ? e.message : String(e), ts: new Date().toISOString(), error: true }]);
    } finally {
      setBusy(false);
    }
  }

  const st = status.data;
  const unavailable = st && (!st.enabled || !st.available);

  return (
    <div className="flex h-[calc(100vh-7.5rem)] flex-col gap-4">
      <PageHeader title="AI Chat"
        subtitle={<>Ask SENTINAL AI about your inventory, this computer and agent activity{st?.model ? ` · ${st.model}` : ""}.</>}
        actions={messages.length ? <Button variant="ghost" onClick={() => setMessages([])}>New conversation</Button> : null} />

      <Notice>
        <span className="inline-flex items-start gap-2">
          <IconLock width={16} height={16} className="mt-0.5 shrink-0 text-accent" />
          <span><b className="text-ink">Read-only mode.</b> In the web chat SENTINAL has no tools: it cannot run commands, connect to computers or change
            anything. It answers from the dashboard data and the agent&apos;s memory. To make a change, send the task to the SENTINAL AI bot in
            Telegram, where every change requires your approval.</span>
        </span>
      </Notice>
      {status.error ? <ErrorBox error={status.error} /> : null}
      {unavailable ? <ErrorBox error={!st.enabled ? "Web chat is disabled (DASHBOARD_CHAT=0 in .env)." : st.blocked || `Claude subscription login is not available: ${st.auth}`} /> : null}

      <Card className="flex min-h-0 flex-1 flex-col" bodyClass="flex min-h-0 flex-1 flex-col p-0">
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5" aria-live="polite">
          {messages.length === 0 ? (
            <div className="mx-auto mt-6 max-w-xl text-center">
              <div className="text-sm text-ink-3">Try one of these:</div>
              <div className="mt-4 flex flex-col gap-2">
                {SUGGESTIONS.map((s) => (
                  <button key={s} onClick={() => send(s)} disabled={busy || !!unavailable}
                    className="rounded-lg border border-line bg-surface-2/60 px-4 py-2.5 text-left text-sm text-ink-2 hover:border-white/20 hover:text-ink disabled:opacity-50">
                    {s}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="mx-auto flex max-w-3xl flex-col gap-4">
              {messages.map((m, i) => (
                <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
                  <div className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed ${m.role === "user" ? "bg-accent/20 text-ink" : m.error ? "border border-critical/40 bg-critical/10 text-ink" : "border border-line bg-surface-2 text-ink"}`}>
                    <div className="whitespace-pre-wrap break-words">{m.content}</div>
                    <div className="mt-1 text-right text-[10px] text-ink-3">{m.role === "user" ? "You" : "SENTINAL"} · {timeOnly(m.ts)}</div>
                  </div>
                </div>
              ))}
              {busy ? (
                <div className="flex justify-start">
                  <div className="rounded-2xl border border-line bg-surface-2 px-4 py-3 text-sm text-ink-3">
                    <span className="inline-flex gap-1"><span className="animate-pulse">●</span><span className="animate-pulse [animation-delay:150ms]">●</span><span className="animate-pulse [animation-delay:300ms]">●</span></span>
                  </div>
                </div>
              ) : null}
              <div ref={endRef} />
            </div>
          )}
        </div>
        <form className="flex items-end gap-2 border-t border-line p-3" onSubmit={(e) => { e.preventDefault(); send(input); }}>
          <textarea value={input} onChange={(e) => setInput(e.target.value)} rows={2} maxLength={4000}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input); } }}
            placeholder={unavailable ? "Chat is unavailable" : "Ask a question… (Enter to send, Shift+Enter for a new line)"}
            disabled={!!unavailable}
            className="min-h-11 flex-1 resize-none rounded-lg border border-line bg-surface-2 px-3 py-2 text-sm text-ink placeholder:text-ink-3 disabled:opacity-50" />
          <Button type="submit" variant="primary" disabled={busy || !input.trim() || !!unavailable}>
            <IconSend width={16} height={16} /> Send
          </Button>
        </form>
      </Card>
    </div>
  );
}
