"""Calendar API snapshots, local date arithmetic and synchronous QuickJS access."""

import asyncio
import copy
import json
from datetime import UTC, datetime

import aiohttp
import calendar_snapshot as calendars
import pytest
from dynamic import definition, worker
from test_dynamic import create, finish


def document(**changes):
    return definition(
        {
            "name": "Calendar",
            "timezone": "Europe/Berlin",
            "calendars": ["calendar.geburtstage"],
            **changes,
        }
    )


def at(value):
    return datetime.fromisoformat(value).timestamp()


def event(summary, start, end):
    key = "dateTime" if "T" in start else "date"
    return {"summary": summary, "start": {key: start}, "end": {key: end}}


class Response:
    def __init__(self, body, status=200):
        self.status = status
        self.body = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.content = self

    async def iter_chunked(self, size):
        for offset in range(0, len(self.body), size):
            yield self.body[offset : offset + size]

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class Session:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = self.responses[url.rsplit("/", 1)[-1]]
        if isinstance(response, Exception):
            raise response
        return response


def test_configuration_defaults_and_validation():
    assert document()["calendar_days"] == 366
    assert document()["calendar_start_of_day"] is True
    assert definition({"name": "Old script"})["calendars"] == []
    assert document(calendars=["calendar.a", "calendar.a"])["calendars"] == [
        "calendar.a"
    ]
    for changes in [
        {"calendars": "calendar.a"},
        {"calendars": ["sensor.a"]},
        {"calendars": ["calendar.a/../../services"]},
        {"calendars": ["calendar.a"] * 9},
        {"calendar_days": 0},
        {"calendar_days": 367},
        {"calendar_days": True},
        {"calendar_start_of_day": "true"},
    ]:
        with pytest.raises(ValueError):
            document(**changes)


@pytest.mark.parametrize(
    "now,expected,seconds",
    [
        ("2026-03-29T16:00:00+02:00", "2026-03-30", 23 * 3600),
        ("2026-10-25T16:00:00+01:00", "2026-10-26", 25 * 3600),
        ("2026-12-31T23:59:00+01:00", "2027-01-01", 24 * 3600),
        ("2028-02-28T23:00:00+01:00", "2028-02-29", 24 * 3600),
    ],
)
def test_local_midnight_windows_cross_dst_year_and_leap_day(now, expected, seconds):
    start, end, today = calendars.window(document(calendar_days=1), at(now))
    assert start.hour == 0 and start.minute == 0
    assert start.date() == today
    assert end.date().isoformat() == expected
    assert (end.astimezone(UTC) - start.astimezone(UTC)).total_seconds() == seconds
    values = calendars.normalize(
        [event("Today", today.isoformat(), expected)],
        "calendar.geburtstage",
        start,
        end,
        today,
    )
    assert values[0]["daysUntil"] == 0
    start, end, today = calendars.window(document(calendar_days=2), at(now))
    values = calendars.normalize(
        [event("Tomorrow", expected, end.date().isoformat())],
        "calendar.geburtstage",
        start,
        end,
        today,
    )
    assert values[0]["daysUntil"] == 1


def test_mixed_events_sort_by_actual_instant_and_use_image_timezone():
    start, end, today = calendars.window(
        document(calendar_days=366), at("2026-11-12T19:00:00+01:00")
    )
    values = calendars.normalize(
        [
            event("Birthday", "2026-12-10", "2026-12-11"),
            event(
                "UTC crosses midnight", "2026-11-12T23:30:00Z", "2026-11-13T00:30:00Z"
            ),
            event(
                "Earlier today",
                "2026-11-12T08:00:00+01:00",
                "2026-11-12T09:00:00+01:00",
            ),
        ],
        "calendar.geburtstage",
        start,
        end,
        today,
    )
    assert [v["summary"] for v in values] == [
        "Earlier today",
        "UTC crosses midnight",
        "Birthday",
    ]
    assert values[1]["start"] == "2026-11-13T00:30:00+01:00"
    assert values[1]["startDate"] == "2026-11-13"
    assert values[1]["daysUntil"] == 1
    assert values[2] == {
        "calendar": "calendar.geburtstage",
        "summary": "Birthday",
        "start": "2026-12-10",
        "end": "2026-12-11",
        "allDay": True,
        "startDate": "2026-12-10",
        "daysUntil": 28,
    }


def test_dst_fold_and_cross_transition_order_is_chronological():
    start, end, today = calendars.window(
        document(calendar_days=1), at("2026-10-25T20:00:00+01:00")
    )
    values = calendars.normalize(
        [
            event(
                "Second 02:15", "2026-10-25T02:15:00+01:00", "2026-10-25T03:00:00+01:00"
            ),
            event(
                "First 02:45", "2026-10-25T02:45:00+02:00", "2026-10-25T02:15:00+01:00"
            ),
        ],
        "calendar.geburtstage",
        start,
        end,
        today,
    )
    assert [v["summary"] for v in values] == ["First 02:45", "Second 02:15"]
    assert all(v["daysUntil"] == 0 for v in values)


def test_start_now_and_end_exclusive_filtering_and_ongoing_events():
    doc = document(calendar_days=1, calendar_start_of_day=False)
    now = at("2026-11-12T18:00:00+01:00")
    start, end, today = calendars.window(doc, now)
    assert start.hour == 18 and end.hour == 18
    values = calendars.normalize(
        [
            event(
                "Earlier today",
                "2026-11-12T10:00:00+01:00",
                "2026-11-12T11:00:00+01:00",
            ),
            event("All day today", "2026-11-12", "2026-11-13"),
            event("Ongoing", "2026-11-11", "2026-11-14"),
            event("Outside", end.isoformat(), "2026-11-13T19:00:00+01:00"),
            event("Point", start.isoformat(), start.isoformat()),
        ],
        "calendar.geburtstage",
        start,
        end,
        today,
    )
    assert [v["summary"] for v in values] == ["Ongoing", "All day today", "Point"]
    assert values[0]["daysUntil"] == -1


async def test_api_is_read_only_bounded_and_empty_calendar_is_explicit():
    session = Session({"calendar.geburtstage": Response([])})
    result = await calendars.snapshot(
        session, "parent-token", document(), at("2026-11-12T18:00:00+01:00")
    )
    assert result == {"calendar.geburtstage": []}
    assert len(session.calls) == 1
    url, options = session.calls[0]
    assert url == "http://supervisor/core/api/calendars/calendar.geburtstage"
    assert options["params"] == {
        "start": "2026-11-12T00:00:00+01:00",
        "end": "2027-11-13T00:00:00+01:00",
    }
    assert options["allow_redirects"] is False
    assert options["headers"] == {"Authorization": "Bearer parent-token"}
    assert await calendars.snapshot(None, None, document(calendars=[]), 0) == {}
    with pytest.raises(ValueError, match="API is unavailable"):
        await calendars.snapshot(None, None, document(), 0)


@pytest.mark.parametrize(
    "response",
    [
        Response([], 401),
        Response([], 404),
        Response([], 500),
        Response([], 302),
        Response(b"not json"),
        Response({"error": "calendar failed"}),
        Response([event("Naive", "2026-11-12T10:00:00", "2026-11-12T11:00:00")]),
        Response([event("Invalid day", "2026-02-30", "2026-03-01")]),
        Response([event("Too long", "2026-11-13", "2026-11-12")]),
        aiohttp.ClientConnectionError("private upstream details"),
        TimeoutError(),
    ],
)
async def test_calendar_errors_are_not_empty_lists(response):
    with pytest.raises(ValueError):
        await calendars.snapshot(
            Session({"calendar.geburtstage": response}),
            "token",
            document(),
            at("2026-11-12T12:00:00+01:00"),
        )


async def test_request_count_event_and_byte_limits(monkeypatch):
    entry = event("Birthday", "2026-11-12", "2026-11-13")
    for response, message in [
        (Response([entry] * 501), "500 events"),
        (Response(b" " * (calendars.MAX_RESPONSE + 1)), "data limit"),
        (Response([event("x" * 2049, "2026-11-12", "2026-11-13")]), "summary"),
    ]:
        with pytest.raises(ValueError, match=message):
            await calendars.snapshot(
                Session({"calendar.geburtstage": response}),
                "token",
                document(),
                at("2026-11-12T12:00:00+01:00"),
            )
    doc = document(calendars=["calendar.a", "calendar.b", "calendar.c"])
    session = Session({name: Response([entry] * 400) for name in doc["calendars"]})
    with pytest.raises(ValueError, match="1000 events"):
        await calendars.snapshot(session, "token", doc, at("2026-11-12T12:00:00+01:00"))
    monkeypatch.setattr(calendars, "MAX_TRANSFER", 1)
    with pytest.raises(ValueError, match="data limit"):
        await calendars.snapshot(
            Session({"calendar.geburtstage": Response([])}), "token", document(), 0
        )


async def test_normalized_snapshot_limit_and_overall_timeout(monkeypatch):
    monkeypatch.setattr(calendars, "MAX_SNAPSHOT", 1)
    with pytest.raises(ValueError, match="256 KiB"):
        await calendars.snapshot(
            Session({"calendar.geburtstage": Response([])}), "token", document(), 0
        )

    async def slow(*args):
        await asyncio.sleep(0.05)

    monkeypatch.setattr(calendars, "fetch", slow)
    original = asyncio.wait_for

    async def short_wait(awaitable, timeout):
        return await original(awaitable, 0.001)

    monkeypatch.setattr(calendars.asyncio, "wait_for", short_wait)
    with pytest.raises(ValueError, match="snapshot timed out"):
        await calendars.snapshot(None, None, document(), 0)


async def test_quickjs_combines_two_events_even_from_same_calendar():
    source = """const events=[...ha.calendarEvents("calendar.abfallkalender"),...ha.calendarEvents("calendar.geburtstage")]
      .filter(e=>e.daysUntil>=0).sort((a,b)=>a.daysUntil-b.daysUntil||a.start.localeCompare(b.start)).slice(0,2);
      for(const e of events)screen.text(`${e.summary}: ${e.daysUntil===0?"Heute":e.daysUntil===1?"Morgen":`in ${e.daysUntil} Tagen`}`);
      if(typeof fetch!=="undefined"||typeof XMLHttpRequest!=="undefined")throw Error("Network exposed");"""
    snapshot = {
        "calendar.abfallkalender": [
            {"summary": "Abholung", "start": "2026-11-20", "daysUntil": 8}
        ],
        "calendar.geburtstage": [
            {"summary": "Example", "start": "2026-11-12", "daysUntil": 0},
            {"summary": "Example B", "start": "2026-11-13", "daysUntil": 1},
        ],
    }
    result = await worker(
        {
            "mode": "commands",
            "source": source,
            "input": {
                "width": 800,
                "height": 600,
                "states": {},
                "calendars": snapshot,
                "palette": {},
                "now": {},
            },
        }
    )
    assert [c["text"] for c in result["commands"]] == ["Example: Heute", "Example B: Morgen"]
    with pytest.raises(ValueError, match="not configured"):
        await worker(
            {
                "mode": "commands",
                "source": 'ha.calendarEvents("calendar.missing");',
                "input": {
                    "width": 800,
                    "height": 600,
                    "states": {},
                    "calendars": snapshot,
                    "palette": {},
                    "now": {},
                },
            }
        )


async def test_one_snapshot_for_all_targets_and_error_preserves_last_good(
    system, monkeypatch
):
    manager, admin, _frames = system
    # Stop the independent scheduler; this test controls render boundaries.
    manager.dynamic.task.cancel()
    await asyncio.gather(manager.dynamic.task, return_exceptions=True)
    monkeypatch.setattr("dynamic.time.time", lambda: at("2026-11-12T18:00:00+01:00"))
    item, target = await create(
        admin,
        calendars=["calendar.geburtstage"],
        calendar_days=366,
        timezone="Europe/Berlin",
        script='screen.text(ha.calendarEvents("calendar.geburtstage")[0].summary);',
    )
    response = await admin.post(
        "/api/dynamic/" + item["id"] + "/targets",
        json={
            "name": "Second target",
            "recipe": {"profile": "inkplate_6", "orientation": "portrait"},
        },
    )
    assert response.status == 201
    second = await response.json()
    session = Session(
        {
            "calendar.geburtstage": Response(
                [event("Example", "2026-12-10", "2026-12-11")]
            )
        }
    )
    monkeypatch.setenv("SUPERVISOR_TOKEN", "parent-only-token")
    original_session = manager.dynamic.session
    manager.dynamic.session = session
    try:
        status = await finish(manager, item["id"])
        assert not status["error"]
        assert len(session.calls) == 1
        before = copy.deepcopy(manager.dynamic.cache)
        session.responses["calendar.geburtstage"] = Response([], 503)
        with pytest.raises(ValueError, match="could not be loaded"):
            await finish(manager, item["id"])
        assert manager.dynamic.cache == before
        assert target["id"] in before and second["id"] in before
        assert manager.dynamic.status(item["id"])["error"]
    finally:
        manager.dynamic.session = original_session


def test_provider_expanded_recurrences_remain_separate_occurrences():
    start, end, today = calendars.window(
        document(calendar_days=366), at("2026-11-12T18:00:00+01:00")
    )
    events = [
        {
            **event("Weekly pickup", "2026-11-13", "2026-11-14"),
            "uid": "same-series",
            "rrule": "FREQ=WEEKLY",
        },
        {
            **event("Weekly pickup", "2026-11-20", "2026-11-21"),
            "uid": "same-series",
            "rrule": "FREQ=WEEKLY",
        },
    ]
    values = calendars.normalize(events, "calendar.abfallkalender", start, end, today)
    assert [v["daysUntil"] for v in values] == [1, 8]
    assert all("rrule" not in v and "uid" not in v for v in values)
