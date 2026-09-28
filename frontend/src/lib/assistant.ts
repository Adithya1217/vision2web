"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { API_URL, ApiError, api, getToken } from "@/lib/api";
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

// Sarvam speech goes through our API (the key stays on the server); these calls send audio, not JSON.
async function voiceFetch(path: string, init: RequestInit): Promise<Response> {
  const token = getToken();
  const res = await fetch(API_URL + path, {
    ...init,
    headers: { ...(init.headers ?? {}), ...(token ? { Authorization: `Bearer ${token}` } : {}) },
  });
  if (!res.ok) throw new ApiError(res.status, "Voice service failed", "voice_failed");
  return res;
}

// Spoken phrases repeat ("How did they pay?"), so keep their audio instead of paying for it again.
// ponytail: simple size cap, no LRU; fine for a session's worth of short prompts.
const ttsCache = new Map<string, string>();

const MAX_RECORDING_MS = 12_000;

export function useAssistant({ onDone }: { onDone?: (title: string) => void } = {}) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [out, setOut] = useState<Interpretation | null>(null);
  const [done, setDone] = useState<DoneStep[] | null>(null);
  const [listening, setListening] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const recRef = useRef<Recognition | null>(null);
  const mediaRef = useRef<MediaRecorder | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const speakTurn = useRef(0);
  // After any Sarvam failure, use the browser's own speech for the rest of the session.
  const [sarvamFailed, setSarvamFailed] = useState(false);
  const voiceStatus = useQuery({
    queryKey: ["voice", "status"],
    queryFn: () => api.get<{ sarvam: boolean }>("/voice/status"),
    staleTime: Infinity,
    retry: false,
  });
  const sarvam = !!voiceStatus.data?.sarvam && !sarvamFailed;
  // A draft created before its post failed: retrying posts it instead of creating a second draft.
  const draftRef = useRef<{ id: number; grand_total: string } | null>(null);
  const submitter = useSubmitter();
  const qc = useQueryClient();

  const browserStt =
    typeof window !== "undefined" && ("SpeechRecognition" in window || "webkitSpeechRecognition" in window);
  const browserTts = typeof window !== "undefined" && "speechSynthesis" in window;
  const canRecord =
    typeof window !== "undefined" && !!navigator.mediaDevices?.getUserMedia && typeof MediaRecorder !== "undefined";
  const voiceEngine: "sarvam" | "browser" = sarvam && canRecord ? "sarvam" : "browser";
  const speechSupported = voiceEngine === "sarvam" || browserStt;
  const ttsSupported = sarvam || browserTts;

  const browserSpeak = (message: string) => {
    if (!browserTts) return setSpeaking(false);
    const utterance = new SpeechSynthesisUtterance(message);
    utterance.lang = "en-IN";
    utterance.onstart = () => setSpeaking(true);
    utterance.onend = () => setSpeaking(false);
    utterance.onerror = () => setSpeaking(false);
    window.speechSynthesis.speak(utterance);
  };

  const stopSpeaking = () => {
    speakTurn.current += 1; // any Sarvam audio still downloading is dropped when it arrives
    audioRef.current?.pause();
    if (browserTts) window.speechSynthesis.cancel();
    setSpeaking(false);
  };

  // Text-to-speech: Sarvam voice when configured, else the browser's. A new message interrupts the last.
  const speak = async (message: string) => {
    if (!message.trim()) return;
    stopSpeaking();
    const turn = speakTurn.current;
    if (!sarvam) return browserSpeak(message);
    setSpeaking(true);
    try {
      let url = ttsCache.get(message);
      if (!url) {
        const res = await voiceFetch("/voice/speak", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: message }),
        });
        url = URL.createObjectURL(await res.blob());
        if (ttsCache.size > 50) ttsCache.clear();
        ttsCache.set(message, url);
      }
      if (turn !== speakTurn.current) return; // interrupted while downloading
      const audio = new Audio(url);
      audioRef.current = audio;
      audio.onended = () => setSpeaking(false);
      await audio.play();
    } catch {
      if (turn !== speakTurn.current) return;
      setSarvamFailed(true);
      browserSpeak(message);
    }
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
      if (mediaRef.current?.state === "recording") mediaRef.current.stop();
      return;
    }
    if (voiceEngine === "sarvam") return recordForSarvam(transform);
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

  // Records until the mic is tapped again (or MAX_RECORDING_MS), then Sarvam transcribes it.
  const recordForSarvam = async (transform: (said: string) => string) => {
    setError(null);
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      setError(new ApiError(0, "Microphone permission is needed to speak commands.", "mic_denied"));
      return;
    }
    const recorder = new MediaRecorder(stream);
    const chunks: Blob[] = [];
    const cap = setTimeout(() => recorder.state === "recording" && recorder.stop(), MAX_RECORDING_MS);
    recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    recorder.onstop = async () => {
      clearTimeout(cap);
      stream.getTracks().forEach((t) => t.stop());
      setListening(false);
      if (mediaRef.current !== recorder) return; // cancelled by stopListening
      const clip = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
      setBusy(true);
      try {
        const res = await voiceFetch("/voice/transcribe", {
          method: "POST",
          headers: { "Content-Type": clip.type },
          body: clip,
        });
        const said = ((await res.json()) as { text: string }).text;
        if (!said) {
          setBusy(false);
          setError(new ApiError(0, "I didn't catch that. Tap the mic and try again.", "no_speech"));
          return;
        }
        setText(said);
        await interpret(transform(said));
      } catch {
        setBusy(false);
        setSarvamFailed(true);
        setError(new ApiError(0, "Voice service is unavailable, so I switched to the built-in voice. Tap the mic again.", "voice_failed"));
      }
    };
    mediaRef.current = recorder;
    recorder.start();
    setListening(true);
  };

  const stopListening = () => {
    recRef.current?.stop();
    const recorder = mediaRef.current;
    mediaRef.current = null; // tells onstop this was a cancel, not a finished command
    if (recorder?.state === "recording") recorder.stop();
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
      label: `Bill ${posted.number ?? ""} saved${pay === "khata" ? " on khata" : ` · paid by ${pay.method === "upi" ? "UPI" : "cash"}`}`,
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
    speaking, ttsSupported, speak, stopSpeaking, voiceEngine,
  };
}
