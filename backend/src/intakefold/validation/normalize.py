import re
import unicodedata

PUNCTUATION = re.compile(r"[^\w\s]")
NOT_ALPHANUMERIC = re.compile(r"[\W_]")


def normalize_vendor(name: str) -> str:
    """Equal for the same name in other casing, spacing or punctuation. Nothing fuzzier."""
    text = unicodedata.normalize("NFKC", name).casefold()
    return " ".join(PUNCTUATION.sub(" ", text).split())


def normalize_invoice_number(number: str) -> str:
    return NOT_ALPHANUMERIC.sub("", unicodedata.normalize("NFKC", number)).upper()


def invoice_keys(
    vendor_name: str | None, invoice_number: str | None
) -> tuple[str | None, str | None]:
    """The duplicate keys of an invoice. A value that normalizes to nothing, such as "—", has no
    key: an empty key would match every other empty one."""
    vendor = normalize_vendor(vendor_name) if vendor_name else ""
    number = normalize_invoice_number(invoice_number) if invoice_number else ""
    return vendor or None, number or None
