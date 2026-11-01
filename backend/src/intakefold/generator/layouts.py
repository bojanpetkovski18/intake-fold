"""Draws documents. Dates and optional fields are drawn only if the plan has them."""
# reportlab ships no type information, so strict checks on its members are off in this file.
# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false, reportMissingTypeStubs=false

import random
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path

import reportlab
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

from intakefold.generator.plan import DocumentPlan, Facts, Line

A4 = (595.0, 842.0)
RECEIPT_WIDTH = 226.0
MARGIN = 48.0
REGULAR = "Vera"
BOLD = "VeraBd"
INK = (0.1, 0.1, 0.1)
MUTED = (0.4, 0.4, 0.4)
WHITE = (1.0, 1.0, 1.0)
DATE_STYLES = ("%Y-%m-%d", "%d %b %Y", "%B %d, %Y")

# Embedded in every PDF, so no page depends on the fonts of the machine that renders it.
FONT_DIRECTORY = Path(reportlab.__file__).parent / "fonts"
pdfmetrics.registerFont(TTFont(REGULAR, str(FONT_DIRECTORY / "Vera.ttf")))
pdfmetrics.registerFont(TTFont(BOLD, str(FONT_DIRECTORY / "VeraBd.ttf")))


class Page:
    def __init__(self, size: tuple[float, float]) -> None:
        self.output = BytesIO()
        self.width, self.height = size
        # invariant fixes the timestamp and file ID, so the same plan gives the same bytes.
        self.canvas = Canvas(self.output, pagesize=size, invariant=1)

    def text(
        self,
        x: float,
        y: float,
        content: str,
        size: float = 9.5,
        font: str = REGULAR,
        color: tuple[float, float, float] = INK,
    ) -> None:
        self.canvas.setFillColorRGB(*color)
        self.canvas.setFont(font, size)
        self.canvas.drawString(x, y, content)

    def right(
        self, x: float, y: float, content: str, size: float = 9.5, font: str = REGULAR
    ) -> None:
        self.canvas.setFillColorRGB(*INK)
        self.canvas.setFont(font, size)
        self.canvas.drawRightString(x, y, content)

    def rule(self, y: float, left: float, right: float) -> None:
        self.canvas.setStrokeColorRGB(*MUTED)
        self.canvas.setLineWidth(0.6)
        self.canvas.line(left, y, right, y)

    def band(self, y: float, height: float, shade: float) -> None:
        self.canvas.setFillColorRGB(shade, shade, shade)
        self.canvas.rect(0, y, self.width, height, stroke=0, fill=1)

    def finish(self) -> bytes:
        self.canvas.showPage()
        self.canvas.save()
        return self.output.getvalue()


def format_date(value: date | None, style: str) -> str | None:
    return value.strftime(style) if value else None


def amount_text(value: Decimal, currency: str | None) -> str:
    return f"{currency} {value:,.2f}" if currency else f"{value:,.2f}"


def identity_rows(facts: Facts, style: str) -> list[tuple[str, str]]:
    number_title = "Invoice No." if facts.document_type == "invoice" else "Receipt No."
    rows = [
        (number_title, facts.invoice_number),
        ("Date", format_date(facts.issue_date, style)),
        ("Due", format_date(facts.due_date, style)),
        ("Currency", facts.currency),
    ]
    return [(title, value) for title, value in rows if value is not None]


def vendor_block(page: Page, x: float, y: float, facts: Facts) -> float:
    vendor = facts.vendor
    for line in (
        f"{vendor.street}, {vendor.city}",
        vendor.email,
        vendor.phone,
        f"Tax ID {vendor.tax_id}",
    ):
        page.text(x, y, line, size=8.5, color=MUTED)
        y -= 12
    return y


def line_table(page: Page, y: float, facts: Facts, columns: tuple[float, float, float]) -> float:
    quantity_x, price_x, amount_x = columns
    page.text(MARGIN, y, "Description", font=BOLD)
    page.right(quantity_x, y, "Qty", font=BOLD)
    page.right(price_x, y, "Unit price", font=BOLD)
    page.right(amount_x, y, "Amount", font=BOLD)
    y -= 6
    page.rule(y, MARGIN, amount_x)
    y -= 15
    for line in facts.lines:
        page.text(MARGIN, y, line.description)
        page.right(quantity_x, y, str(line.quantity))
        page.right(price_x, y, f"{line.unit_price:,.2f}")
        page.right(amount_x, y, f"{line.amount:,.2f}")
        y -= 16
    return y - 4


def totals(page: Page, y: float, title_x: float, value_x: float, facts: Facts) -> float:
    rows = [("Subtotal", facts.subtotal), ("Tax", facts.tax_total)]
    if facts.adjustments_total:
        rows.append(("Adjustments", facts.adjustments_total))
    for title, value in rows:
        page.text(title_x, y, title)
        page.right(value_x, y, f"{value:,.2f}")
        y -= 15
    page.rule(y + 10, title_x, value_x)
    page.text(title_x, y - 4, "Total", size=11, font=BOLD)
    page.right(value_x, y - 4, amount_text(facts.total, facts.currency), size=11, font=BOLD)
    return y - 24


def closing_notes(page: Page, y: float, plan: DocumentPlan) -> None:
    terms = "Payment within 30 days." if plan.facts.document_type == "invoice" else "Thank you."
    injection = plan.injection
    if injection is not None and injection.placement == "payment_terms":
        terms = f"{terms} {injection.text}"
    page.text(MARGIN, y, terms, size=8.5, color=MUTED)
    if injection is None:
        return
    if injection.placement == "footer":
        page.text(MARGIN, 30, injection.text, size=7.5, color=MUTED)
    elif injection.placement == "hidden":
        page.text(MARGIN, 18, injection.text, size=2, color=WHITE)


def classic(plan: DocumentPlan, style: str) -> bytes:
    page = Page(A4)
    facts = plan.facts
    top = page.height - MARGIN - 8
    page.text(MARGIN, top, facts.vendor.name, size=16, font=BOLD)
    vendor_block(page, MARGIN, top - 18, facts)
    y = top
    page.right(page.width - MARGIN, y, "INVOICE", size=14, font=BOLD)
    y -= 20
    for title, value in identity_rows(facts, style):
        page.right(page.width - MARGIN, y, f"{title}: {value}")
        y -= 13
    y = line_table(page, top - 120, facts, (370, 450, page.width - MARGIN))
    y = totals(page, y, 350, page.width - MARGIN, facts)
    closing_notes(page, y - 20, plan)
    return page.finish()


def banded(plan: DocumentPlan, style: str) -> bytes:
    page = Page(A4)
    facts = plan.facts
    page.band(page.height - 96, 96, 0.9)
    page.text(MARGIN, page.height - 44, facts.vendor.name, size=18, font=BOLD)
    page.text(MARGIN, page.height - 62, "Tax invoice", size=10, color=MUTED)
    y = page.height - 122
    for title, value in identity_rows(facts, style):
        page.text(MARGIN, y, title, font=BOLD)
        page.text(MARGIN + 80, y, value)
        y -= 14
    vendor_block(page, 340, page.height - 122, facts)
    y = line_table(page, page.height - 212, facts, (360, 450, page.width - MARGIN))
    y = totals(page, y, 340, page.width - MARGIN, facts)
    closing_notes(page, y - 20, plan)
    return page.finish()


def compact(plan: DocumentPlan, style: str) -> bytes:
    page = Page(A4)
    facts = plan.facts
    y = page.height - MARGIN
    page.text(MARGIN, y, f"{facts.vendor.name} / Invoice", size=13, font=BOLD)
    y -= 16
    page.text(MARGIN, y, " | ".join(f"{t}: {v}" for t, v in identity_rows(facts, style)), size=8.5)
    y -= 20
    y = vendor_block(page, MARGIN, y, facts) - 14
    y = line_table(page, y, facts, (380, 460, page.width - MARGIN))
    y = totals(page, y, 380, page.width - MARGIN, facts)
    closing_notes(page, y - 16, plan)
    return page.finish()


def ledger(plan: DocumentPlan, style: str) -> bytes:
    page = Page(A4)
    facts = plan.facts
    page.band(page.height - 56, 2, 0.2)
    page.text(MARGIN, page.height - 44, "BILL", size=20, font=BOLD)
    page.right(page.width - MARGIN, page.height - 44, facts.vendor.name, size=13, font=BOLD)
    vendor_block(page, 340, page.height - 74, facts)
    y = page.height - 74
    for title, value in identity_rows(facts, style):
        page.text(MARGIN, y, f"{title}  {value}")
        y -= 13
    y = line_table(page, page.height - 190, facts, (340, 430, page.width - MARGIN))
    y = totals(page, y, 300, page.width - MARGIN, facts)
    closing_notes(page, y - 20, plan)
    return page.finish()


def receipt(plan: DocumentPlan, style: str) -> bytes:
    facts = plan.facts
    height = 300.0 + 14 * len(facts.lines)
    page = Page((RECEIPT_WIDTH, height))
    left, right = 14.0, RECEIPT_WIDTH - 14
    y = height - 26
    page.text(left, y, facts.vendor.name, size=10, font=BOLD)
    y -= 14
    page.text(left, y, f"{facts.vendor.street}, {facts.vendor.city}", size=6.5, color=MUTED)
    y -= 10
    page.text(left, y, f"Tax ID {facts.vendor.tax_id}", size=6.5, color=MUTED)
    y -= 16
    for title, value in identity_rows(facts, style):
        page.text(left, y, f"{title}: {value}", size=7.5)
        y -= 11
    y -= 6
    page.rule(y, left, right)
    y -= 13
    for line in facts.lines:
        page.text(left, y, line_summary(line), size=6.5)
        page.right(right, y, f"{line.amount:,.2f}", size=7.5)
        y -= 14
    y -= 2
    for title, value in (
        ("Subtotal", facts.subtotal),
        ("Tax", facts.tax_total),
        ("Adjustments", facts.adjustments_total),
    ):
        if title != "Adjustments" or value:
            page.text(left, y, title, size=7.5)
            page.right(right, y, f"{value:,.2f}", size=7.5)
            y -= 12
    page.text(left, y - 4, "Total", size=9, font=BOLD)
    page.right(right, y - 4, amount_text(facts.total, facts.currency), size=9, font=BOLD)
    return page.finish()


def line_summary(line: Line) -> str:
    return f"{line.quantity} x {line.description} @ {line.unit_price:,.2f}"


LAYOUTS: dict[str, Callable[[DocumentPlan, str], bytes]] = {
    "classic": classic,
    "banded": banded,
    "compact": compact,
    "ledger": ledger,
    "receipt": receipt,
}


def draw_pdf(plan: DocumentPlan) -> bytes:
    # Seeded from the plan alone, so one document's look never depends on another.
    style = random.Random(plan.render_seed).choice(DATE_STYLES)  # noqa: S311 - not security
    return LAYOUTS[plan.layout](plan, style)
