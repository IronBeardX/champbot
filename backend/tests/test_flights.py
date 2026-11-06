from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from champbot.common.flights.domain.flight import Cabin, Flight
from champbot.common.flights.presentation.dependencies import get_flight_search
from champbot.main import create_app

A_SERVED_MONDAY = "2026-11-09"
AN_UNSERVED_TUESDAY = "2026-11-10"


class FakeFlightSearch:
    def __init__(self, flights: list[Flight] | None = None) -> None:
        self.flights = flights or []
        self.calls: list[tuple[str, str, date]] = []

    async def search(self, origin: str, destination: str, departure_date: date) -> list[Flight]:
        self.calls.append((origin, destination, departure_date))
        return self.flights


def client_with(search: FakeFlightSearch) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_flight_search] = lambda: search
    return TestClient(app)


def test_served_route_returns_the_schedule() -> None:
    response = TestClient(create_app()).get(
        "/flights", params={"origin": "DEL", "destination": "LHR", "date": A_SERVED_MONDAY}
    )

    assert response.status_code == 200
    body = response.json()
    assert body == [
        {
            "flight_number": "AI 111",
            "origin": "DEL",
            "destination": "LHR",
            "departure": "2026-11-09T13:30:00",
            "arrival": "2026-11-09T18:20:00",
            "duration_minutes": 620,
            "fares": {"economy": 48000, "business": 180000},
            "currency": "INR",
        }
    ]


@pytest.mark.parametrize(
    ("origin", "destination", "search_date"),
    [
        pytest.param("DEL", "LHR", AN_UNSERVED_TUESDAY, id="unserved-weekday"),
        pytest.param("BLR", "JFK", A_SERVED_MONDAY, id="unserved-route"),
        pytest.param("DEL", "ZZZ", A_SERVED_MONDAY, id="unknown-well-formed-airport"),
        pytest.param("DEL", "DEL", A_SERVED_MONDAY, id="same-origin-and-destination"),
    ],
)
def test_no_matching_flights_returns_200_with_an_empty_list(
    origin: str, destination: str, search_date: str
) -> None:
    response = TestClient(create_app()).get(
        "/flights", params={"origin": origin, "destination": destination, "date": search_date}
    )

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.parametrize(
    "params",
    [
        pytest.param({"destination": "LHR", "date": A_SERVED_MONDAY}, id="missing-origin"),
        pytest.param({"origin": "DEL", "date": A_SERVED_MONDAY}, id="missing-destination"),
        pytest.param({"origin": "DEL", "destination": "LHR"}, id="missing-date"),
        pytest.param(
            {"origin": "DE", "destination": "LHR", "date": A_SERVED_MONDAY}, id="origin-too-short"
        ),
        pytest.param(
            {"origin": "DELH", "destination": "LHR", "date": A_SERVED_MONDAY},
            id="origin-too-long",
        ),
        pytest.param(
            {"origin": "del", "destination": "LHR", "date": A_SERVED_MONDAY},
            id="origin-lowercase",
        ),
        pytest.param(
            {"origin": "D3L", "destination": "LHR", "date": A_SERVED_MONDAY}, id="origin-digit"
        ),
        pytest.param(
            {"origin": "", "destination": "LHR", "date": A_SERVED_MONDAY}, id="origin-empty"
        ),
        pytest.param(
            {"origin": "DEL", "destination": "LHR", "date": "2026/11/09"}, id="date-wrong-separator"
        ),
        pytest.param(
            {"origin": "DEL", "destination": "LHR", "date": "09-11-2026"}, id="date-wrong-order"
        ),
        pytest.param(
            {"origin": "DEL", "destination": "LHR", "date": "2026-02-30"},
            id="date-does-not-exist",
        ),
        pytest.param(
            {"origin": "DEL", "destination": "LHR", "date": "2026-11-09T00:00:00"},
            id="date-is-a-datetime",
        ),
        pytest.param(
            {"origin": "DEL", "destination": "LHR", "date": "1762646400"},
            id="date-is-a-timestamp",
        ),
        pytest.param({"origin": "DEL", "destination": "LHR", "date": ""}, id="date-empty"),
    ],
)
def test_malformed_input_is_rejected_before_reaching_the_adapter(params: dict[str, str]) -> None:
    search = FakeFlightSearch()

    response = client_with(search).get("/flights", params=params)

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
    assert search.calls == []


def test_valid_query_is_forwarded_to_the_adapter_and_results_keep_their_order() -> None:
    first = Flight(
        flight_number="AI 2401",
        origin="DEL",
        destination="BOM",
        departure=datetime(2026, 11, 9, 7, 0),
        arrival=datetime(2026, 11, 9, 9, 10),
        duration=timedelta(hours=2, minutes=10),
        fares={Cabin.ECONOMY: 5000, Cabin.BUSINESS: 18000},
    )
    search = FakeFlightSearch([first])

    response = client_with(search).get(
        "/flights", params={"origin": "DEL", "destination": "BOM", "date": A_SERVED_MONDAY}
    )

    assert response.status_code == 200
    assert [flight["flight_number"] for flight in response.json()] == ["AI 2401"]
    assert search.calls == [("DEL", "BOM", date(2026, 11, 9))]
