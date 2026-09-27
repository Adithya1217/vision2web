// Fixed-point money helpers. Amounts travel as decimal strings ("1234.50") and are handled as integer
// paise (bigint) for any client-side arithmetic. The server is always the authority for totals.

const MONEY_RE = /^-?\d+(\.\d{1,2})?$/;

export function isMoney(value: string): boolean {
  return MONEY_RE.test(value.trim());
}

export function toPaise(value: string | number | null | undefined): bigint {
  if (value === null || value === undefined || value === "") return 0n;
  const s = String(value).trim();
  if (!/^-?\d+(\.\d+)?$/.test(s)) throw new Error(`invalid decimal: ${s}`);
  const negative = s.startsWith("-");
  const [intPart, frac = ""] = s.replace("-", "").split(".");
  const cents = BigInt(intPart) * 100n + BigInt((frac + "00").slice(0, 2));
  // round half-up on the third decimal, if any
  const third = frac.length > 2 && Number(frac[2]) >= 5 ? 1n : 0n;
  const result = cents + third;
  return negative ? -result : result;
}

export function fromPaise(paise: bigint): string {
  const negative = paise < 0n;
  const abs = negative ? -paise : paise;
  const whole = abs / 100n;
  const frac = (abs % 100n).toString().padStart(2, "0");
  return `${negative ? "-" : ""}${whole}.${frac}`;
}

/** Divide and round half-up (away from zero), matching the backend's ROUND_HALF_UP. */
export function divRound(numerator: bigint, denominator: bigint): bigint {
  const negative = numerator < 0n !== denominator < 0n;
  const n = numerator < 0n ? -numerator : numerator;
  const d = denominator < 0n ? -denominator : denominator;
  const q = (n * 2n + d) / (2n * d);
  return negative ? -q : q;
}

function groupIndian(digits: string): string {
  if (digits.length <= 3) return digits;
  const last3 = digits.slice(-3);
  const rest = digits.slice(0, -3).replace(/\B(?=(\d{2})+(?!\d))/g, ",");
  return `${rest},${last3}`;
}

/** Format a decimal string as Indian rupees without ever converting to a float. */
export function formatINR(value: string | null | undefined, opts: { symbol?: boolean; compact?: boolean } = {}) {
  if (value === null || value === undefined || value === "") return "—";
  const s = fromPaise(toPaise(value));
  const negative = s.startsWith("-");
  const [whole, frac] = s.replace("-", "").split(".");
  const symbol = opts.symbol === false ? "" : "₹";
  if (opts.compact) {
    const n = BigInt(whole);
    if (n >= 10000000n) return `${negative ? "-" : ""}${symbol}${fromPaise((n * 100n) / 10000000n)}Cr`;
    if (n >= 100000n) return `${negative ? "-" : ""}${symbol}${fromPaise((n * 100n) / 100000n)}L`;
    if (n >= 1000n) return `${negative ? "-" : ""}${symbol}${fromPaise((n * 100n) / 1000n)}K`;
  }
  return `${negative ? "-" : ""}${symbol}${groupIndian(whole)}.${frac}`;
}

export interface LineEstimate {
  gross: bigint;
  discount: bigint;
  taxable: bigint;
  cgst: bigint;
  sgst: bigint;
  igst: bigint;
  total: bigint;
}

/** Mirror of the backend line calculation, for live previews only. */
export function estimateLine(
  quantity: number,
  unitPrice: string,
  gstRate: string,
  discount: { amount?: string; percent?: string },
  intraState: boolean,
): LineEstimate {
  const gross = toPaise(unitPrice) * BigInt(quantity);
  const rateBp = toPaise(gstRate); // "18.00" -> 1800 (basis points)
  let disc = 0n;
  if (discount.percent) disc = divRound(gross * toPaise(discount.percent), 10000n);
  else if (discount.amount) disc = toPaise(discount.amount);
  if (disc > gross) disc = gross;
  const taxable = gross - disc;
  let cgst = 0n;
  let sgst = 0n;
  let igst = 0n;
  if (intraState) {
    cgst = divRound(taxable * rateBp, 20000n);
    sgst = cgst;
  } else {
    igst = divRound(taxable * rateBp, 10000n);
  }
  return { gross, discount: disc, taxable, cgst, sgst, igst, total: taxable + cgst + sgst + igst };
}
