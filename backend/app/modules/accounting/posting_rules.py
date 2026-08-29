from dataclasses import dataclass
from decimal import Decimal

ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class PostingLine:
    system_code: str
    debit: Decimal = ZERO
    credit: Decimal = ZERO
    description: str | None = None


def cash_sale(
    net: Decimal, tax: Decimal, cost: Decimal
) -> tuple[list[PostingLine], list[PostingLine]]:
    revenue = [
        PostingLine("CASH", debit=net + tax),
        PostingLine("SALES_REVENUE", credit=net),
    ]
    if tax:
        revenue.append(PostingLine("VAT_OUTPUT", credit=tax))
    cost_entry = [PostingLine("COGS", debit=cost), PostingLine("INVENTORY", credit=cost)]
    return revenue, cost_entry


def credit_sale(net: Decimal, tax: Decimal) -> list[PostingLine]:
    lines = [PostingLine("AR_CONTROL", debit=net + tax), PostingLine("SALES_REVENUE", credit=net)]
    if tax:
        lines.append(PostingLine("VAT_OUTPUT", credit=tax))
    return lines


def customer_payment(amount: Decimal, *, cash: bool) -> list[PostingLine]:
    return [
        PostingLine("CASH" if cash else "BANK", debit=amount),
        PostingLine("AR_CONTROL", credit=amount),
    ]


def sales_return(
    net: Decimal, tax: Decimal, cost: Decimal = ZERO
) -> tuple[list[PostingLine], list[PostingLine] | None]:
    revenue = [PostingLine("SALES_RETURNS", debit=net)]
    if tax:
        revenue.append(PostingLine("VAT_OUTPUT", debit=tax))
    revenue.append(PostingLine("AR_CONTROL", credit=net + tax))
    cost_entry = None
    if cost:
        cost_entry = [PostingLine("INVENTORY", debit=cost), PostingLine("COGS", credit=cost)]
    return revenue, cost_entry


def pos_refund(
    net: Decimal, tax: Decimal, cost: Decimal, *, restock: bool
) -> tuple[list[PostingLine], list[PostingLine] | None]:
    revenue = [PostingLine("SALES_RETURNS", debit=net)]
    if tax:
        revenue.append(PostingLine("VAT_OUTPUT", debit=tax))
    revenue.append(PostingLine("CASH", credit=net + tax))
    return revenue, (
        [PostingLine("INVENTORY", debit=cost), PostingLine("COGS", credit=cost)]
        if restock and cost
        else None
    )
