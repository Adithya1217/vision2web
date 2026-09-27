from decimal import Decimal
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field


def _reject_float(value: Any) -> Any:
    if isinstance(value, float):
        raise ValueError("send money/rates as a decimal string (e.g. \"12.50\"), not a float")
    if isinstance(value, bool):
        raise ValueError("invalid number")
    return value


def _money_scale(value: Decimal) -> Decimal:
    if not value.is_finite():
        raise ValueError("must be a finite number")
    if value.as_tuple().exponent < -2:  # type: ignore[operator]
        raise ValueError("at most 2 decimal places")
    return value.quantize(Decimal("0.01"))


MoneyIn = Annotated[
    Decimal, BeforeValidator(_reject_float), AfterValidator(_money_scale), Field(ge=0, max_digits=14)
]
PositiveMoneyIn = Annotated[
    Decimal, BeforeValidator(_reject_float), AfterValidator(_money_scale), Field(gt=0, max_digits=14)
]
RateIn = Annotated[
    Decimal, BeforeValidator(_reject_float), AfterValidator(_money_scale), Field(ge=0, le=100, max_digits=5)
]
StateCode = Annotated[str, Field(pattern=r"^\d{2}$", description="Two-digit GST state code, e.g. 29")]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
