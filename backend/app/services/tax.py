"""GST arithmetic. Prices are tax-exclusive; every line is rounded to paise, invoice totals are line sums."""

from dataclasses import dataclass, field
from decimal import Decimal

from app.core.money import HUNDRED, ZERO, q
from app.enums import SupplyType

TWO = Decimal("2")


def supply_type_for(shop_state: str, place_of_supply: str) -> SupplyType:
    return SupplyType.intra_state if shop_state == place_of_supply else SupplyType.inter_state


def discount_from(gross: Decimal, amount: Decimal | None, percent: Decimal | None) -> Decimal:
    if amount is not None and percent is not None:
        raise ValueError("give either discount_amount or discount_percent, not both")
    if percent is not None:
        return q(gross * percent / HUNDRED)
    return q(amount or ZERO)


@dataclass(frozen=True)
class LineAmounts:
    gross: Decimal
    discount: Decimal
    taxable: Decimal
    cgst: Decimal
    sgst: Decimal
    igst: Decimal
    total: Decimal


def compute_line(
    quantity: int, unit_price: Decimal, gst_rate: Decimal, discount: Decimal, supply: SupplyType
) -> LineAmounts:
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    gross = q(unit_price * quantity)
    discount = q(discount)
    if discount < ZERO or discount > gross:
        raise ValueError("discount must be between 0 and the line amount")
    taxable = gross - discount
    if supply == SupplyType.intra_state:
        half_rate = gst_rate / TWO
        cgst = q(taxable * half_rate / HUNDRED)
        sgst = cgst
        igst = ZERO
    else:
        cgst = sgst = ZERO
        igst = q(taxable * gst_rate / HUNDRED)
    return LineAmounts(gross, discount, taxable, cgst, sgst, igst, taxable + cgst + sgst + igst)


@dataclass
class Totals:
    subtotal: Decimal = ZERO
    discount_total: Decimal = ZERO
    taxable_total: Decimal = ZERO
    cgst_total: Decimal = ZERO
    sgst_total: Decimal = ZERO
    igst_total: Decimal = ZERO
    grand_total: Decimal = ZERO
    lines: list[LineAmounts] = field(default_factory=list)

    def add(self, line: LineAmounts) -> None:
        self.lines.append(line)
        self.subtotal += line.gross
        self.discount_total += line.discount
        self.taxable_total += line.taxable
        self.cgst_total += line.cgst
        self.sgst_total += line.sgst
        self.igst_total += line.igst
        self.grand_total += line.total


def prorate(original: Decimal, part_qty: int, total_qty: int) -> Decimal:
    return q(original * part_qty / total_qty)
