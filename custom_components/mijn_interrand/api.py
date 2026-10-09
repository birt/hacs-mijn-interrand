"""Client for the Mijn Interrand customer portal (www.mijninterrand.be).

The portal has no public API. Logging in is a plain form POST that sets an
ASP.NET session cookie. The balance and collection dates are server-rendered
into the HTML, and the transactions come from a DataTables JSON endpoint.

This module has no Home Assistant imports so it can be tested on its own.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

import aiohttp

BASE_URL = "https://www.mijninterrand.be"
LOGON_PATH = "/Account/Logon"
VERRICHTINGEN_PATH = "/Aansluitpunten/Verrichtingen"
VERRICHTINGEN_JSON_PATH = "/Aansluitpunten/ShowResultsVerrichtingen"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)
BROWSER_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "nl-BE,nl;q=0.9,en;q=0.8",
}
AJAX_HEADERS = {
    **BROWSER_HEADERS,
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": BASE_URL + VERRICHTINGEN_PATH,
}

_SALDO_RE = re.compile(
    r">\s*Huidig saldo\s*</label>.*?<input[^>]*\bvalue=\"([^\"]*)\"", re.S | re.I
)
_COLLECTION_RE = re.compile(
    r"<li>\s*Volgende inzameling\s+([^<]+?)\s*<span[^>]*>\s*<strong>\s*([^<]*?)\s*</strong>",
    re.I,
)
_DETAIL_RE = re.compile(
    r"<li>\s*(Klantnummer|Aantal bewoners|Referentiepersoon)\s*<span[^>]*>\s*<strong>\s*([^<]*?)\s*</strong>",
    re.I,
)
_OGM_RE = re.compile(r"id=\"AansluitpuntDetail_Ogm\"[^>]*\bvalue=\"(\d+)\"", re.I)
_ADDRESS_BLOCK_RE = re.compile(r"<ul class=\"persondetails right\">(.*?)</ul>", re.S | re.I)
_LI_RE = re.compile(r"<li[^>]*>(.*?)</li>", re.S | re.I)
_WEIGHT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*kg\b", re.I)
_TAG_RE = re.compile(r"<[^>]+>")


class InterrandError(Exception):
    """Generic error talking to the portal."""


class InterrandAuthError(InterrandError):
    """Login was rejected."""


@dataclass
class Transaction:
    date: Optional[date]
    type: str
    description: str
    amount: Optional[Decimal]

    @property
    def weight_kg(self) -> Optional[float]:
        match = _WEIGHT_RE.search(self.description)
        return float(match.group(1).replace(",", ".")) if match else None

    def as_dict(self) -> dict[str, Any]:
        return {
            "date": self.date.isoformat() if self.date else None,
            "type": self.type,
            "description": self.description,
            "amount": float(self.amount) if self.amount is not None else None,
        }


@dataclass
class InterrandData:
    balance: Optional[Decimal]
    collections: dict[str, Optional[date]] = field(default_factory=dict)
    customer_number: Optional[str] = None
    address: Optional[str] = None
    residents: Optional[int] = None
    ogm: Optional[str] = None
    transactions: list[Transaction] = field(default_factory=list)
    transaction_count: Optional[int] = None


def parse_amount(text: str) -> Optional[Decimal]:
    """Parse a Belgian formatted amount like '€ -1.234,56'."""
    cleaned = html.unescape(_TAG_RE.sub("", text))
    cleaned = cleaned.replace("€", "").replace("\xa0", "").replace(" ", "")
    cleaned = cleaned.replace(".", "").replace(",", ".")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def parse_date(text: str) -> Optional[date]:
    try:
        return datetime.strptime(text.strip(), "%d/%m/%Y").date()
    except ValueError:
        return None


def format_ogm(ogm: str) -> str:
    """Format a 12 digit OGM as +++123/4567/89012+++."""
    if len(ogm) != 12:
        return ogm
    return f"+++{ogm[:3]}/{ogm[3:7]}/{ogm[7:]}+++"


def parse_verrichtingen_page(page: str) -> InterrandData:
    match = _SALDO_RE.search(page)
    if not match:
        raise InterrandError("Could not find 'Huidig saldo' on the page")
    data = InterrandData(balance=parse_amount(match.group(1)))

    for name, value in _COLLECTION_RE.findall(page):
        data.collections[html.unescape(name).strip().lower()] = parse_date(value)

    for label, value in _DETAIL_RE.findall(page):
        label = label.lower()
        if label == "klantnummer":
            data.customer_number = value
        elif label == "aantal bewoners" and value.isdigit():
            data.residents = int(value)

    if match := _OGM_RE.search(page):
        data.ogm = format_ogm(match.group(1))
    if match := _ADDRESS_BLOCK_RE.search(page):
        for item in _LI_RE.findall(match.group(1)):
            text = " ".join(html.unescape(_TAG_RE.sub("", item)).split())
            if text and not text.lower().startswith("volgende inzameling"):
                data.address = text
                break
    return data


def parse_transactions(payload: dict[str, Any]) -> list[Transaction]:
    result = []
    for row in payload.get("aaData", []):
        if len(row) < 4:
            continue
        result.append(
            Transaction(
                date=parse_date(row[0]),
                type=html.unescape(_TAG_RE.sub("", row[1])).strip(),
                description=html.unescape(_TAG_RE.sub("", row[2])).strip(),
                amount=parse_amount(row[3]),
            )
        )
    return result


class InterrandClient:
    """Async client. Pass a session that has its own cookie jar."""

    def __init__(self, session: aiohttp.ClientSession, username: str, password: str) -> None:
        self._session = session
        self._username = username
        self._password = password
        self._logged_in = False

    async def login(self) -> None:
        headers = BROWSER_HEADERS
        try:
            # Prime the session cookie the same way a browser would.
            async with self._session.get(BASE_URL + LOGON_PATH, headers=headers) as resp:
                await resp.read()
            async with self._session.post(
                BASE_URL + LOGON_PATH,
                headers={**headers, "Referer": BASE_URL + LOGON_PATH},
                data={
                    "Identifier": self._username,
                    "AuthenticationValue": self._password,
                    "LogonByName": "Aanmelden",
                    "RememberMe": "false",
                },
            ) as resp:
                resp.raise_for_status()
                await resp.read()
                final_path = resp.url.path
        except (aiohttp.ClientError, TimeoutError) as err:
            raise InterrandError(f"Error connecting to Mijn Interrand: {err}") from err

        if final_path.lower().startswith(LOGON_PATH.lower()):
            self._logged_in = False
            raise InterrandAuthError("Invalid username or password")
        self._logged_in = True

    async def _get(self, path: str, params: Optional[dict[str, Any]] = None, *, json: bool = False) -> Any:
        """GET a page, logging in (again) when the session is missing or expired."""
        if not self._logged_in:
            await self.login()
        for attempt in range(2):
            headers = AJAX_HEADERS if json else BROWSER_HEADERS
            try:
                async with self._session.get(BASE_URL + path, params=params, headers=headers) as resp:
                    resp.raise_for_status()
                    expired = resp.url.path.lower().startswith(LOGON_PATH.lower())
                    if not expired:
                        if json:
                            return await resp.json(content_type=None)
                        return await resp.text()
            except (aiohttp.ClientError, TimeoutError) as err:
                raise InterrandError(f"Error fetching {path}: {err}") from err
            except ValueError as err:
                raise InterrandError(f"Invalid JSON from {path}: {err}") from err
            if attempt == 0:
                await self.login()
        raise InterrandError(f"Still redirected to the login page when fetching {path}")

    async def fetch_transactions(self, count: int = 10) -> tuple[list[Transaction], Optional[int]]:
        payload = await self._get(
            VERRICHTINGEN_JSON_PATH,
            {
                "sEcho": 1,
                "sSearchFilter": "[]",
                "DisplayStart": 0,
                "DisplayLength": count,
                "SearchQuery": "",
                "Verrichtingtypeid": "",
            },
            json=True,
        )
        if not isinstance(payload, dict):
            raise InterrandError("Unexpected response for transactions")
        return parse_transactions(payload), payload.get("iTotalRecords")

    async def fetch(self, transaction_count: int = 10) -> InterrandData:
        page = await self._get(VERRICHTINGEN_PATH)
        data = parse_verrichtingen_page(page)
        data.transactions, data.transaction_count = await self.fetch_transactions(transaction_count)
        return data
