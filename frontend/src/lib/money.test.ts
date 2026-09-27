import assert from "node:assert/strict";
import { test } from "node:test";

import { divRound, estimateLine, formatINR, fromPaise, toPaise } from "./money.ts";

test("parses and prints without floats", () => {
  assert.equal(toPaise("0.1") + toPaise("0.2"), 30n);
  assert.equal(fromPaise(toPaise("1234.5")), "1234.50");
  assert.equal(fromPaise(-5n), "-0.05");
});

test("indian grouping", () => {
  assert.equal(formatINR("1234567.8"), "₹12,34,567.80");
  assert.equal(formatINR("999"), "₹999.00");
  assert.equal(formatINR("-100000"), "-₹1,00,000.00");
  assert.equal(formatINR("2500000", { compact: true }), "₹25.00L");
});

test("half-up rounding matches backend", () => {
  assert.equal(divRound(5n, 2n), 3n);
  assert.equal(divRound(-5n, 2n), -3n);
});

test("line estimate matches backend fixtures", () => {
  const a = estimateLine(2, "100.00", "18", { percent: "10" }, true);
  assert.equal(fromPaise(a.taxable), "180.00");
  assert.equal(fromPaise(a.cgst), "16.20");
  assert.equal(fromPaise(a.total), "212.40");
  const b = estimateLine(3, "33.33", "5", { amount: "0.99" }, true);
  assert.equal(fromPaise(b.cgst), "2.48");
  assert.equal(fromPaise(b.total), "103.96");
  const c = estimateLine(3, "33.33", "5", { amount: "0.99" }, false);
  assert.equal(fromPaise(c.igst), "4.95");
});
