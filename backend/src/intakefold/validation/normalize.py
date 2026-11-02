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
