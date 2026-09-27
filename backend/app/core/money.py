"""Fixed-point money helpers. Floats are never accepted anywhere in the money path."""

from decimal import ROUND_HALF_UP, Decimal

PAISA = Decimal("0.01")
ZERO = Decimal("0.00")
HUNDRED = Decimal("100")


def to_decimal(value: Decimal | int | str) -> Decimal:
    if isinstance(value, float):  # pragma: no cover - defensive
        raise TypeError("floats are not allowed for money")
    return value if isinstance(value, Decimal) else Decimal(str(value))


def q(value: Decimal | int | str) -> Decimal:
    """Quantize to paise using commercial (half-up) rounding."""
    return to_decimal(value).quantize(PAISA, rounding=ROUND_HALF_UP)


def pct(amount: Decimal, rate: Decimal) -> Decimal:
    return q(amount * rate / HUNDRED)
