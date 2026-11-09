import type { Tone } from "@/components/kit";

/** Ijro hayot sikli (backend: agent/trading/lifecycle.py). Eski "CONFIRMED" ijro degani EMAS — faqat EXECUTED MT5 DEMO order_send. */
export const EXEC_TONE: Record<string, Tone> = {
  GENERATED: "mute", WATCH: "warn", DEBATE_PENDING: "info", DEBATE_APPROVED: "info", DEBATE_REJECTED: "bad",
  RISK_VALIDATION_PENDING: "info", EXECUTION_READY: "info", EXECUTED: "good", EXECUTION_REFUSED: "bad", INVALIDATED: "mute", EXPIRED: "mute",
};

export const ORIGIN_LABEL: Record<string, string> = { auto: "AUTO", manual: "QO'LDA (HA)", forced_test: "MAJBURIY SINOV", test: "TEST" };
