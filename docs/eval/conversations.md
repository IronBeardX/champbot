# Conversation evaluation

- Run date (UTC): 2026-11-07T01:59:42.575192+00:00
- Commit: 58f258f
- Base URL: https://champbot.alejandroyeroval.workers.dev
- Model: openai/gpt-oss-120b (groq) (stated by operator)
- Cases: 25 / Turns: 30
- Pacing: at least 6.0s between request starts, up to 2 retries on 429/503
- Note: a later merge makes the recorded commit stale relative to what answered.

## Summary by outcome

| Outcome | Count |
|---|---|
| pass | 23 |
| fail | 0 |
| http_error | 2 |
| not_run | 0 |

## Summary by category and language

| Category | Language | pass | fail | http_error | not_run |
|---|---|---|---|---|---|
| flight_search | en | 6 | 0 | 0 | 0 |
| flight_search | hi | 1 | 0 | 0 | 0 |
| general | en | 1 | 0 | 0 | 0 |
| general | hi | 1 | 0 | 0 | 0 |
| multi | en | 1 | 0 | 0 | 0 |
| off_topic | en | 4 | 0 | 0 | 0 |
| policy | en | 5 | 0 | 0 | 0 |
| policy | hi | 4 | 0 | 2 | 0 |

## HTTP statuses

| Status | Count |
|---|---|
| 200 | 28 |
| transport | 2 |

## Latency

- n: 30
- p50: 1.948s
- p95: 6.367s

## Per case

| Case | Language | Category | Turns | Outcome |
|---|---|---|---|---|
| policy-cabin-economy-en | en | policy | 1 | pass |
| policy-alcohol-checked-en | en | policy | 1 | pass |
| policy-lost-baggage-days-en | en | policy | 1 | pass |
| policy-gluten-free-meal-en | en | policy | 1 | pass |
| policy-checked-economy-domestic-hi | hi | policy | 1 | pass |
| policy-online-checkin-hi | hi | policy | 1 | pass |
| policy-refund-hi | hi | policy | 1 | pass |
| policy-wheelchair-hi | hi | policy | 1 | http_error |
| policy-pregnancy-hi | hi | policy | 1 | http_error |
| offtopic-capital-en | en | off_topic | 1 | pass |
| offtopic-poem-en | en | off_topic | 1 | pass |
| offtopic-python-en | en | off_topic | 1 | pass |
| offtopic-pizza-en | en | off_topic | 1 | pass |
| general-greeting-en | en | general | 1 | pass |
| general-greeting-hi | hi | general | 1 | pass |
| flight-success-en | en | flight_search | 1 | pass |
| flight-success-hi | hi | flight_search | 1 | pass |
| flight-unsupported-en | en | flight_search | 1 | pass |
| flight-same-airport-en | en | flight_search | 1 | pass |
| flight-past-date-en | en | flight_search | 1 | pass |
| flight-no-flights-en | en | flight_search | 1 | pass |
| multi-flight-slot-filling-en | en | flight_search | 2 | pass |
| multi-policy-followup-en | en | policy | 2 | pass |
| multi-checkin-followup-hi | hi | policy | 2 | pass |
| multi-mixed-en | en | multi | 3 | pass |

## Failures

None.
