"""Client-local vendor mapping (vendors.json): email domains / login patterns -> vendor label.

The mapping itself (domains, patterns) is used in memory only and never reaches a report or
the export. Labels appear in the client's own report; the export carries a salted hash of
each label unless the client passes --keep-vendor-names.

File format:
  {"vendors": [{"label": "Acme Dev", "email_domains": ["acme.example"], "logins": ["^acme-"]}]}
Login patterns are case-insensitive regular expressions searched in the GitHub login.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from .pr_review import HUMAN, OTHER_BOT, UNKNOWN, author_class

LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._()+\-]{0,39}$")
DOMAIN_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")
_NOREPLY_RE = re.compile(r"^(?:\d+\+)?(?P<login>[^@]+)@users\.noreply\.github\.com$")


class VendorFileError(ValueError):
    pass


@dataclass(frozen=True)
class Vendor:
    label: str
    domains: frozenset[str]
    logins: tuple[re.Pattern, ...]


@dataclass(frozen=True)
class Vendors:
    entries: tuple[Vendor, ...]

    @property
    def labels(self) -> tuple[str, ...]:
        return tuple(v.label for v in self.entries)


def _strings(entry: dict, key: str) -> tuple[str, ...]:
    value = entry.get(key, [])
    if not isinstance(value, list) or not all(isinstance(x, str) and x.strip() for x in value):
        raise VendorFileError(f"vendors file: '{key}' must be a list of non-empty strings")
    return tuple(x.strip() for x in value)


def _vendor(entry) -> Vendor:
    if not isinstance(entry, dict):
        raise VendorFileError("vendors file: each vendor must be an object")
    label = entry.get("label")
    if not isinstance(label, str) or not LABEL_RE.match(label):
        raise VendorFileError("vendors file: label must be 1-40 chars of letters, digits, space . _ ( ) + -")
    domains = tuple(d.lower() for d in _strings(entry, "email_domains"))
    bad = [d for d in domains if not DOMAIN_RE.match(d)]
    if bad:
        raise VendorFileError(f"vendors file: invalid email domain for vendor {label}")
    try:
        logins = tuple(re.compile(p, re.I) for p in _strings(entry, "logins"))
    except re.error as exc:
        raise VendorFileError(f"vendors file: bad login pattern for vendor {label}: {exc}") from None
    if not domains and not logins:
        raise VendorFileError(f"vendors file: vendor {label} needs email_domains or logins")
    return Vendor(label, frozenset(domains), logins)


def load_vendors(path) -> Vendors:
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise VendorFileError(f"vendors file unreadable: {type(exc).__name__}") from None
    raw = data.get("vendors") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        raise VendorFileError("vendors file: top-level 'vendors' list missing")
    entries = tuple(_vendor(e) for e in raw)
    if len({v.label for v in entries}) != len(entries):
        raise VendorFileError("vendors file: duplicate labels")
    return Vendors(entries)


def vendor_for_login(vendors: Vendors | None, login: str) -> str | None:
    if not vendors or not login:
        return None
    norm = login.strip()
    return next((v.label for v in vendors.entries if any(p.search(norm) for p in v.logins)), None)


def vendor_for_email(vendors: Vendors | None, email: str) -> str | None:
    if not vendors or not email:
        return None
    addr = email.strip().lower()
    noreply = _NOREPLY_RE.match(addr)
    if noreply:
        return vendor_for_login(vendors, noreply.group("login"))
    domain = addr.rpartition("@")[2]
    for v in vendors.entries:
        if any(domain == d or domain.endswith("." + d) for d in v.domains):
            return v.label
    return None


def pr_class(person, vendors: Vendors | None) -> tuple[str, str | None]:
    """(group, vendor label) for a PR author. Precedence: vendor, then agent, then human."""
    login = str(person.get("login") or "") if isinstance(person, dict) else ""
    label = vendor_for_login(vendors, login)
    if label:
        return "vendor", label
    cls = author_class(person)
    if cls in (HUMAN, OTHER_BOT, UNKNOWN):
        return cls, None
    return "agent", None


def vendor_id(label: str, keep: bool = False) -> str:
    """Export id: salted sha256 so short vendor names cannot be guessed from a dictionary."""
    if keep:
        return label
    salt = os.environ.get("AEMS_EXPORT_SALT", "")
    return hashlib.sha256((salt + "vendor:" + label).encode()).hexdigest()[:12]
