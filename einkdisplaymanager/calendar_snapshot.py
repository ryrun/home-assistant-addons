"""Bounded read-only HA calendar snapshots, normalized in the image's time zone."""

import asyncio
import json
import re
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import aiohttp

MAX_CALENDARS = 8
MAX_DAYS = 366
MAX_EVENTS_PER_CALENDAR = 500
MAX_EVENTS = 1000
MAX_RESPONSE = 256 * 1024
MAX_TRANSFER = 1024 * 1024
MAX_SNAPSHOT = 256 * 1024
CALENDAR_ID = re.compile(r"calendar\.[a-z0-9_]+\Z")


def settings(document):
    calendars = document.get("calendars", [])
    if (
        not isinstance(calendars, list)
        or len(calendars) > MAX_CALENDARS
        or any(
            not isinstance(v, str) or not CALENDAR_ID.fullmatch(v) for v in calendars
        )
    ):
        raise ValueError("Use at most 8 calendar.* entity IDs.")
    days = document.get("calendar_days", MAX_DAYS)
    if type(days) is not int or not 1 <= days <= MAX_DAYS:
        raise ValueError("Calendar look-ahead must be 1–366 whole days.")
    start_of_day = document.get("calendar_start_of_day", True)
    if type(start_of_day) is not bool:
        raise ValueError("Calendar start-of-day must be a boolean.")
    return {
        "calendars": sorted(set(calendars)),
        "calendar_days": days,
        "calendar_start_of_day": start_of_day,
    }


def window(document, now):
    zone = ZoneInfo(document["timezone"])
    local = datetime.fromtimestamp(now, zone)
    start = (
        datetime.combine(local.date(), time.min, zone)
        if document.get("calendar_start_of_day", True)
        else local
    )
    # Add calendar days in the image zone, not multiples of 86400 UTC seconds.
    return (
        start,
        start + timedelta(days=document.get("calendar_days", MAX_DAYS)),
        local.date(),
    )


def boundary(value, zone):
    if not isinstance(value, dict):
        raise ValueError("Invalid calendar event date.")  # noqa: TRY004 — remote data validation.
    if "date" in value and "dateTime" not in value:
        text = value["date"]
        if not isinstance(text, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            raise ValueError("Invalid all-day calendar date.")
        day = date.fromisoformat(text)
        return day.isoformat(), datetime.combine(day, time.min, zone), True
    text = value.get("dateTime")
    if (
        "date" in value
        or not isinstance(text, str)
        or len(text) > 80
        or "T" not in text
    ):
        raise ValueError("Invalid timed calendar date.")
    instant = datetime.fromisoformat(text)
    if instant.utcoffset() is None:
        raise ValueError("Timed calendar events require a time zone offset.")
    local = instant.astimezone(zone)
    return local.isoformat(), local, False


def normalize(events, calendar, start, end, today):
    if not isinstance(events, list):
        raise ValueError("Calendar API returned an invalid event list.")  # noqa: TRY004 — remote data validation.
    if len(events) > MAX_EVENTS_PER_CALENDAR:
        raise ValueError("Calendar exceeds 500 events; reduce the look-ahead period.")
    result = []
    zone = start.tzinfo
    for event in events:
        if not isinstance(event, dict) or not isinstance(event.get("summary"), str):
            raise ValueError("Calendar API returned an invalid event.")  # noqa: TRY004 — remote data validation.
        summary = event["summary"]
        if len(summary.encode()) > 2048:
            raise ValueError("Calendar event summary exceeds its size limit.")
        first, begins, all_day = boundary(event.get("start"), zone)
        last, ends, end_all_day = boundary(event.get("end"), zone)
        # Compare instants: two 02:30 occurrences at the autumn DST transition
        # can have identical local wall times but different UTC offsets.
        begin_utc, end_utc = (
            begins.astimezone(UTC),
            ends.astimezone(UTC),
        )
        if (
            all_day != end_all_day
            or end_utc < begin_utc
            or (all_day and end_utc == begin_utc)
        ):
            raise ValueError("Calendar event has an invalid date range.")
        if (
            begin_utc >= end.astimezone(UTC)
            or (end_utc <= start.astimezone(UTC) and begin_utc != end_utc)
            or (begin_utc == end_utc and begin_utc < start.astimezone(UTC))
        ):
            continue
        result.append(
            (
                begin_utc,
                {
                    "calendar": calendar,
                    "summary": summary,
                    "start": first,
                    "end": last,
                    "allDay": all_day,
                    "startDate": begins.date().isoformat(),
                    "daysUntil": (begins.date() - today).days,
                },
            )
        )
    result.sort(key=lambda item: item[0])
    return [item for _, item in result]


async def fetch(session, token, document, now):
    config = settings(document)
    if not config["calendars"]:
        return {}
    if not token or session is None:
        raise ValueError(
            "Home Assistant API is unavailable. Calendar rendering requires the installed add-on with API access."
        )
    start, end, today = window({**document, **config}, now)
    result, transferred, count = {}, 0, 0
    for calendar in config["calendars"]:
        try:
            async with session.get(
                "http://supervisor/core/api/calendars/" + calendar,
                params={"start": start.isoformat(), "end": end.isoformat()},
                headers={"Authorization": "Bearer " + token},
                allow_redirects=False,
            ) as response:
                if response.status != 200:
                    raise ValueError(
                        f"Calendar {calendar} could not be loaded (HTTP {response.status}); the last good image is retained."
                    )
                chunks, size = [], 0
                async for block in response.content.iter_chunked(16384):
                    size += len(block)
                    transferred += len(block)
                    if size > MAX_RESPONSE or transferred > MAX_TRANSFER:
                        raise ValueError(
                            "Calendar response exceeds its data limit; reduce the look-ahead period."
                        )
                    chunks.append(block)
                events = json.loads(b"".join(chunks))
                if isinstance(events, list):
                    count += len(events)
                    if count > MAX_EVENTS:
                        raise ValueError(
                            "Calendar snapshot exceeds 1000 events; reduce the look-ahead period."
                        )
                result[calendar] = normalize(events, calendar, start, end, today)
        except (aiohttp.ClientError, TimeoutError):
            raise ValueError(
                f"Calendar {calendar} is unavailable; the last good image is retained."
            ) from None
        except (json.JSONDecodeError, UnicodeError, OverflowError):
            raise ValueError(
                f"Calendar {calendar} returned invalid data; the last good image is retained."
            ) from None
    if len(json.dumps(result, ensure_ascii=False).encode()) > MAX_SNAPSHOT:
        raise ValueError(
            "Calendar snapshot exceeds 256 KiB; reduce the look-ahead period."
        )
    return result


async def snapshot(session, token, document, now):
    try:
        return await asyncio.wait_for(fetch(session, token, document, now), 10)
    except TimeoutError:
        raise ValueError(
            "Calendar snapshot timed out; the last good image is retained."
        ) from None
