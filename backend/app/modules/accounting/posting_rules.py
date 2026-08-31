from dataclasses import dataclass
from decimal import Decimal

ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class PostingLine:
    system_code: str
    debit: Decimal = ZERO
    credit: Decimal = ZERO
    description: str | None = None


def cogs_recognition(cost: Decimal) -> list[PostingLine]:
    """COGS DR / Inventory CR — the pair every cost-recognition entry in this
    system reduces to. Used directly where cost is recognised on its own
    (a sales fulfillment, decoupled in time from invoice revenue); `cash_sale`
    and `pos_refund` below inline the same two lines because they return it
    paired with a revenue entry from the same call."""
    return [PostingLine("COGS", debit=cost), PostingLine("INVENTORY", credit=cost)]


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


def goods_receipt(cost: Decimal) -> list[PostingLine]:
    """ACCOUNTING.md §3.4. Receipt and bill are deliberately separate events
    — goods often arrive before the invoice, and GRNI is the standard bridge
    so inventory is never misstated waiting on paperwork."""
    return [PostingLine("INVENTORY", debit=cost), PostingLine("GRNI", credit=cost)]


def supplier_bill(goods_cost: Decimal, tax: Decimal) -> list[PostingLine]:
    """ACCOUNTING.md §3.5. Clears the GRNI bridge and recognises the
    liability and reclaimable input VAT."""
    lines = [PostingLine("GRNI", debit=goods_cost)]
    if tax:
        lines.append(PostingLine("VAT_INPUT", debit=tax))
    lines.append(PostingLine("AP_CONTROL", credit=goods_cost + tax))
    return lines


def supplier_payment(amount: Decimal, *, cash: bool) -> list[PostingLine]:
    """ACCOUNTING.md §3.6."""
    return [
        PostingLine("AP_CONTROL", debit=amount),
        PostingLine("CASH" if cash else "BANK", credit=amount),
    ]
