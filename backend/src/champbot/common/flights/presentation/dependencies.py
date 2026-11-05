from champbot.common.flights.domain.search import FlightSearch
from champbot.common.flights.infrastructure.schedule_template import ScheduleTemplateFlightSearch


def get_flight_search() -> FlightSearch:
    return ScheduleTemplateFlightSearch()
