"""Invented vendors. Each name was searched before use; see docs/RESEARCH.md."""

from dataclasses import dataclass


@dataclass(frozen=True)
class VendorProfile:
    name: str
    aliases: tuple[str, ...]
    street: str
    city: str
    email: str
    phone: str  # 555-01xx is reserved for fiction.
    tax_id: str


def normalized_name(name: str) -> str:
    return " ".join(name.lower().split())


# Seeded into `vendors`, so these pass `known_vendor`.
KNOWN_VENDORS = (
    VendorProfile(
        "Brindlecote Stationers",
        ("Brindlecote",),
        "14 Example Row",
        "Sampleton",
        "accounts@brindlecote.example.com",
        "+1 202 555 0101",
        "FAKE-TAX-1001",
    ),
    VendorProfile(
        "Tarnwell Freight",
        ("Tarnwell Freight Co",),
        "2 Placeholder Quay",
        "Mockport",
        "billing@tarnwell.example.com",
        "+1 202 555 0102",
        "FAKE-TAX-1002",
    ),
    VendorProfile(
        "Morrowfen Catering",
        (),
        "88 Fictional Lane",
        "Sampleton",
        "hello@morrowfen.example.com",
        "+1 202 555 0103",
        "FAKE-TAX-1003",
    ),
    VendorProfile(
        "Ostrel Print Works",
        ("Ostrel Print",),
        "6 Specimen Yard",
        "Testbury",
        "orders@ostrel.example.com",
        "+1 202 555 0104",
        "FAKE-TAX-1004",
    ),
    VendorProfile(
        "Harrowmere Cleaning Services",
        ("Harrowmere Cleaning",),
        "31 Demo Avenue",
        "Mockport",
        "office@harrowmere.example.com",
        "+1 202 555 0105",
        "FAKE-TAX-1005",
    ),
    VendorProfile(
        "Velloway Electrical",
        (),
        "9 Invented Close",
        "Testbury",
        "jobs@velloway.example.com",
        "+1 202 555 0106",
        "FAKE-TAX-1006",
    ),
    VendorProfile(
        "Cindergate Joinery",
        (),
        "47 Sample Street",
        "Sampleton",
        "workshop@cindergate.example.com",
        "+1 202 555 0107",
        "FAKE-TAX-1007",
    ),
    VendorProfile(
        "Pellandine Water Supply",
        ("Pellandine Water",),
        "120 Mock Road",
        "Testbury",
        "billing@pellandine.example.com",
        "+1 202 555 0108",
        "FAKE-TAX-1008",
    ),
)

# Never seeded, so these fail `known_vendor`.
UNKNOWN_VENDORS = (
    VendorProfile(
        "Drovemoor Tools",
        (),
        "5 Nowhere Mews",
        "Fauxford",
        "sales@drovemoor.example.com",
        "+1 202 555 0111",
        "FAKE-TAX-2001",
    ),
    VendorProfile(
        "Lunnick Textiles",
        (),
        "73 Imaginary Hill",
        "Fauxford",
        "trade@lunnick.example.com",
        "+1 202 555 0112",
        "FAKE-TAX-2002",
    ),
    VendorProfile(
        "Zenthorpe Packaging",
        (),
        "18 Pretend Parade",
        "Fauxford",
        "supply@zenthorpe.example.com",
        "+1 202 555 0113",
        "FAKE-TAX-2003",
    ),
)
