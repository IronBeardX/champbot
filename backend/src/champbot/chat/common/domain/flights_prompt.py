FLIGHTS_PROMPT = """Flight search instructions. Today is {today} in India (IST). To turn a day
the user names into a date, look it up in this table of the next seven days instead of
calculating it. "Tomorrow" is the first row; "Friday", "this Friday" and "next Friday" all
mean the Friday in the table:
{date_table}
For any other date, use the exact date the user gave. A date given without a year means
the next such date on or after today.

For "flight_search", fill flight_query from the whole conversation, keeping any detail from
an earlier turn that the user has not changed:
- origin and destination: the airport code of the city the user named, from this list:
  {airports}. Use "UNSUPPORTED" for a city or airport that is not in the list. Use null when
  the user has not named it yet. Never guess a city the user did not name.
- date: the departure date as YYYY-MM-DD, or null when the user has not given one.

When origin, destination and date are all known, the answer is one short, neutral sentence
that names the route and the date, such as "Flights from Delhi to London on Friday 6
November 2026:". Do not say whether there are flights. When a city is "UNSUPPORTED", the
answer is one short sentence acknowledging the request, without promising results.
Otherwise, ask only for what is still missing.

Never write flight numbers, times, fares or availability yourself: the system adds them
after your answer."""

FLIGHTS_DATE_ROW = "- {weekday}: {iso_date}"

FLIGHTS_AIRPORT = "{city} {code}"
