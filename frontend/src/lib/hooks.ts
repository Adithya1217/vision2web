"use client";

import { useEffect, useState } from "react";

import { createSubmitter } from "./api";

export function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

/** One idempotency-key submitter per form instance (see createSubmitter). */
export function useSubmitter() {
  const [submitter] = useState(createSubmitter);
  return submitter;
}
