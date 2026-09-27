"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { api } from "@/lib/api";
import { useSubmitter } from "@/lib/hooks";

// Shared by the command bar and simple mode: interpret text, then run the proposed API calls only after
// the user confirms. /ai/interpret itself never changes data.

export interface ProposedAction {
  method: "POST" | "PUT" | "PATCH";
  path: string;
  body: Record<string, unknown>;
  label: string;
}
export interface Candidate {
  id: number;
  label: string;
  detail: string | null;
}
export interface Interpretation {
  text: string;
  intent: string;
  kind: "read" | "write";
  source: "rules" | "llm";
  confidence: number;
  entities: {
    items: { query: string; quantity: number }[];
    product_query: string | null;
    customer_query: string | null;
  };
  message: string;
  result: unknown;
  proposal: {
    title: string;
    summary: string[];
    actions: ProposedAction[];
    warnings: string[];
    permitted: boolean;
    ready: boolean;
    preview: { grand_total?: string; note?: string } | null;
  } | null;
  candidates: Record<string, Candidate[]>;
}
// How a sale was paid. Given to confirm(), a sale is saved and posted in one go (stock drops, the
// sale counts today); without it the command bar keeps its old behaviour of leaving a draft.
export type PayChoice = { method: "cash" | "upi" } | "khata";

export interface DoneStep {
  label: string;
  href?: string;
}

// Minimal typing for the Web Speech API (not in lib.dom for all browsers).
type Recognition = {
  lang: string;
  interimResults: boolean;
  onresult: (e: { results: { 0: { transcript: string } }[] }) => void;
  onend: () => void;
  onerror: () => void;
  start: () => void;
  stop: () => void;
};

export function useAssistant({ onDone }: { onDone?: (title: string) => void } = {}) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [out, setOut] = useState<Interpretation | null>(null);
  const [done, setDone] = useState<DoneStep[] | null>(null);
  const [listening, setListening] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const recRef = useRef<Recognition | null>(null);
  // A draft created before its post failed: retrying posts it instead of creating a second draft.
  const draftRef = useRef<{ id: number; grand_total: string } | null>(null);
  const submitter = useSubmitter();
  const qc = useQueryClient();

  const speechSupported =
    typeof window !== "undefined" && ("SpeechRecognition" in window || "webkitSpeechRecognition" in window);

  const ttsSupported = typeof window !== "undefined" && "speechSynthesis" in window;

  // Text-to-speech: reads a message aloud; a new message interrupts the previous one.
  const speak = (message: string) => {
    if (!ttsSupported || !message.trim()) return;
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(message);
    utterance.lang = "en-IN";
    utterance.onstart = () => setSpeaking(true);
    utterance.onend = () => setSpeaking(false);
    utterance.onerror = () => setSpeaking(false);
    window.speechSynthesis.speak(utterance);
  };

  const stopSpeaking = () => {
    if (!ttsSupported) return;
    window.speechSynthesis.cancel();
    setSpeaking(false);
  };

  const interpret = async (value = text) => {
    if (!value.trim()) return;
    draftRef.current = null;
    setBusy(true);
    setError(null);
    setOut(null);
    setDone(null);
    try {
      setOut(await api.post<Interpretation>("/ai/interpret", { text: value }));
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  // `transform` lets simple mode turn "Ramesh 500" into "Ramesh paid 500" before interpreting.
  const listen = (transform: (said: string) => string = (s) => s) => {
    if (listening) {
      recRef.current?.stop();
      return;
    }
    const W = window as unknown as Record<string, new () => Recognition>;
    const Ctor = W.SpeechRecognition ?? W.webkitSpeechRecognition;
    if (!Ctor) return;
    const rec = new Ctor();
    rec.lang = "en-IN";
    rec.interimResults = false;
    rec.onresult = (e) => {
      const said = e.results[0][0].transcript;
      setText(said);
      interpret(transform(said));
    };
    rec.onend = () => setListening(false);
    rec.onerror = () => setListening(false);
    recRef.current = rec;
    setListening(true);
    rec.start();
  };

  const stopListening = () => {
    recRef.current?.stop();
    setListening(false);
  };

  const confirm = async (pay?: PayChoice) => {
    if (!out?.proposal) return;
    setBusy(true);
    setError(null);
    const results: DoneStep[] = [];
    try {
      for (const action of out.proposal.actions) {
        const isSale = action.path === "/invoices";
        if (isSale && pay) {
          results.push(await sell(action, pay));
          continue;
        }
        const key = submitter.keyFor({ path: action.path, body: action.body });
        const method = action.method.toLowerCase() as "post" | "put" | "patch";
        const res = await api[method]<{ id?: number; invoice_id?: number }>(action.path, action.body, key);
        submitter.done();
        const href = isSale && res && "id" in res ? `/invoices/${res.id}` : undefined;
        results.push({ label: action.label, href });
      }
      setDone(results);
      onDone?.(out.proposal.title);
      qc.invalidateQueries();
    } catch (err) {
      setError(err);
      if (results.length) setDone(results);
    } finally {
      setBusy(false);
    }
  };

  const sell = async (action: ProposedAction, pay: PayChoice): Promise<DoneStep> => {
    if (!draftRef.current) {
      const key = submitter.keyFor({ path: action.path, body: action.body });
      draftRef.current = await api.post<{ id: number; grand_total: string }>(action.path, action.body, key);
      submitter.done();
    }
    const draft = draftRef.current;
    const path = `/invoices/${draft.id}/post`;
    // Paid now: settle the full server-computed total. On khata: no payment, the balance goes to the ledger.
    const body = { payments: pay === "khata" ? [] : [{ method: pay.method, amount: draft.grand_total }] };
    const posted = await api.post<{ number: string | null }>(path, body, submitter.keyFor({ path, body }));
    submitter.done();
    draftRef.current = null;
    return {
      label: `Bill ${posted.number ?? ""} saved${pay === "khata" ? " on khata" : ` · paid by ${pay.method.toUpperCase()}`}`,
      href: `/invoices/${draft.id}`,
    };
  };

  const reset = () => {
    draftRef.current = null;
    setText("");
    setOut(null);
    setDone(null);
    setError(null);
  };

  return {
    text, setText, busy, error, out, done, listening, speechSupported, interpret, listen, stopListening, confirm, reset,
    speaking, ttsSupported, speak, stopSpeaking,
  };
}
