"""Client for the Recycle! app API (www.recycleapp.be), run by Fost Plus.

This is the public API the recycleapp.be website uses. It needs no account,
only the website's consumer header.

This module has no Home Assistant imports so it can be tested on its own.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

import aiohttp

API_URL = "https://api.fostplus.be/recyclecms/public/v1"
LANGUAGE = "nl"
TZ = ZoneInfo("Europe/Brussels")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "nl-BE,nl;q=0.9,en;q=0.8",
    "Origin": "https://www.recycleapp.be",
    "Referer": "https://www.recycleapp.be/",
    "x-consumer": "recycleapp.be",
}

_ADDRESS_RE = re.compile(r"^\s*(.+?)\s+(\d+\S*)\s*,\s*(\d{4})\s+(.+?)\s*$")


class RecycleError(Exception):
    """Error talking to the Recycle! API."""


class RecycleNotFound(RecycleError):
    """Zipcode or street not found."""


@dataclass
class Zipcode:
    id: str
    code: str
    city: str


@dataclass
class Street:
    id: str
    name: str


@dataclass
class Collection:
    date: date
    fraction_id: str
    fraction_name: str
    color: Optional[str]

    @property
    def short_name(self) -> str:
        """'GFT - Groenten-, fruit- en tuinafval' -> 'GFT'."""
        return self.fraction_name.split(" - ")[0].strip()


@dataclass
class RecyclingPark:
    id: str
    name: str
    address: str
    # ISO weekday (1 = Monday) -> list of (from, until)
    weekly: dict[int, list[tuple[time, time]]] = field(default_factory=dict)
    # Date -> list of (from, until); an empty list means closed that day.
    exceptions: dict[date, list[tuple[time, time]]] = field(default_factory=dict)

    def hours_on(self, day: date) -> list[tuple[time, time]]:
        if day in self.exceptions:
            return self.exceptions[day]
        return self.weekly.get(day.isoweekday(), [])

    def is_open(self, moment: datetime) -> bool:
        local = moment.astimezone(TZ)
        return any(start <= local.time() < end for start, end in self.hours_on(local.date()))

    def _intervals_from(self, moment: datetime, days: int = 21):
        local = moment.astimezone(TZ)
        for offset in range(days):
            day = local.date() + timedelta(days=offset)
            for start, end in sorted(self.hours_on(day)):
                yield (
                    datetime.combine(day, start, TZ),
                    datetime.combine(day, end, TZ),
                )

    def next_opening(self, moment: datetime) -> Optional[datetime]:
        return next((s for s, _ in self._intervals_from(moment) if s > moment), None)

    def next_closing(self, moment: datetime) -> Optional[datetime]:
        return next((e for s, e in self._intervals_from(moment) if s <= moment < e), None)


def split_address(address: str) -> Optional[tuple[str, str, str, str]]:
    """'Eeuwfeestplein 17, 3090 Overijse' -> (street, number, zipcode, city)."""
    match = _ADDRESS_RE.match(address)
    return match.groups() if match else None  # type: ignore[return-value]


def _name(names: Any) -> str:
    if isinstance(names, dict):
        return names.get(LANGUAGE) or next(iter(names.values()), "")
    return str(names or "")


def _local_date(timestamp: str) -> date:
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(TZ).date()


def _hours(items: list[dict[str, Any]]) -> list[tuple[time, time]]:
    return [(time.fromisoformat(h["from"]), time.fromisoformat(h["until"])) for h in items]


def parse_collections(items: list[dict[str, Any]]) -> list[Collection]:
    result = []
    for item in items:
        if item.get("type") != "collection" or not item.get("fraction"):
            continue
        # A collection that was moved to another day is listed twice: the
        # original with "replacedBy" and the new date with "replaces".
        if (item.get("exception") or {}).get("replacedBy"):
            continue
        fraction = item["fraction"]
        result.append(
            Collection(
                date=_local_date(item["timestamp"]),
                fraction_id=fraction["id"],
                fraction_name=_name(fraction.get("name")),
                color=fraction.get("color"),
            )
        )
    return sorted(result, key=lambda c: (c.date, c.fraction_name))


def parse_recycling_park(item: dict[str, Any]) -> RecyclingPark:
    address = " ".join(
        part.strip()
        for part in (item.get("street", "").title(), item.get("houseNumber", ""))
        if part.strip()
    )
    city = " ".join(
        part.strip() for part in (item.get("zipcode", ""), item.get("city", "")) if part.strip()
    )
    park = RecyclingPark(
        id=item["id"],
        name=_name(item.get("displayName") or item.get("name")),
        address=", ".join(part for part in (address, city) if part),
    )
    today = datetime.now(TZ).date()
    for period in item.get("openingPeriods", []):
        if not _local_date(period["from"]) <= today <= _local_date(period["until"]):
            continue
        for day in period.get("openingDays", []):
            # ISO weekdays; accept 0 for Sunday as well.
            park.weekly[day["day"] or 7] = _hours(day.get("openingHours", []))
    for exception in item.get("exceptionDays", []):
        hours = _hours(exception.get("openingHours", [])) if exception.get("open") else []
        park.exceptions[_local_date(exception["date"])] = hours
    return park


class RecycleClient:
    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session

    async def _request(self, method: str, path: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            async with self._session.request(
                method, API_URL + path, params=params, headers=HEADERS
            ) as resp:
                resp.raise_for_status()
                return await resp.json(content_type=None)
        except aiohttp.ClientError as err:
            raise RecycleError(f"Error fetching {path}: {err}") from err
        except ValueError as err:
            raise RecycleError(f"Invalid JSON from {path}: {err}") from err

    async def find_zipcode(self, code: str, city: Optional[str] = None) -> Zipcode:
        data = await self._request("GET", "/zipcodes", {"q": code})
        matches = [
            Zipcode(id=item["id"], code=item["code"], city=_name(item.get("city", {}).get("names")))
            for item in data.get("items", [])
            if item.get("code") == code and item.get("available", True)
        ]
        if city and len(matches) > 1:
            matches = [z for z in matches if z.city.lower() == city.lower()] or matches
        if not matches:
            raise RecycleNotFound(f"Zipcode {code} not found")
        return matches[0]

    async def find_street(self, zipcode_id: str, street: str) -> Street:
        data = await self._request("POST", "/streets", {"q": street, "zipcodes": zipcode_id})
        streets = [
            Street(id=item["id"], name=_name(item.get("names")) or item.get("name", ""))
            for item in data.get("items", [])
            if not item.get("deleted")
        ]
        exact = [s for s in streets if s.name.lower() == street.strip().lower()]
        if exact:
            return exact[0]
        if len(streets) == 1:
            return streets[0]
        raise RecycleNotFound(f"Street {street} not found")

    async def get_collections(
        self, zipcode_id: str, street_id: str, house_number: str, start: date, end: date
    ) -> list[Collection]:
        items: list[dict[str, Any]] = []
        page = 1
        while True:
            data = await self._request(
                "GET",
                "/collections",
                {
                    "zipcodeId": zipcode_id,
                    "streetId": street_id,
                    "houseNumber": house_number,
                    "fromDate": start.isoformat(),
                    "untilDate": end.isoformat(),
                    "size": 100,
                    "page": page,
                },
            )
            items.extend(data.get("items", []))
            if page >= int(data.get("pages") or 1) or page >= 10:
                break
            page += 1
        return parse_collections(items)

    async def get_recycling_parks(self, zipcode_id: str) -> list[RecyclingPark]:
        data = await self._request(
            "GET",
            "/collection-points/recycling-parks",
            {"zipcode": zipcode_id, "size": 100, "language": LANGUAGE},
        )
        return [
            parse_recycling_park(item)
            for item in data.get("items", [])
            if item.get("active", True) and not item.get("deleted")
        ]
