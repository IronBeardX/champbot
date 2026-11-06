export const CABIN_LABELS = {
  economy: "Economy",
  business: "Business",
};

const AIRPORT_CODE_PATTERN = /^[A-Z]{3}$/;
const CURRENCY_PATTERN = /^[A-Z]{3}$/;
const DATE_TIME_PATTERN = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})(?::\d{2})?$/;

function parseDateTime(raw) {
  if (typeof raw !== "string") {
    return null;
  }
  const match = DATE_TIME_PATTERN.exec(raw);
  return match === null ? null : { date: match[1], time: match[2] };
}

function readFares(raw) {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) {
    return [];
  }
  const fares = [];
  for (const cabin of Object.keys(CABIN_LABELS)) {
    const amount = raw[cabin];
    if (Number.isInteger(amount) && amount >= 0) {
      fares.push({ cabin, amount });
    }
  }
  return fares;
}

function readDurationMinutes(raw) {
  return Number.isInteger(raw) && raw > 0 ? raw : null;
}

function readFlight(raw) {
  if (typeof raw !== "object" || raw === null) {
    return null;
  }
  const { flight_number: flightNumber, origin, destination, currency } = raw;
  if (typeof flightNumber !== "string" || flightNumber.trim() === "") {
    return null;
  }
  if (typeof origin !== "string" || !AIRPORT_CODE_PATTERN.test(origin)) {
    return null;
  }
  if (typeof destination !== "string" || !AIRPORT_CODE_PATTERN.test(destination)) {
    return null;
  }
  if (typeof currency !== "string" || !CURRENCY_PATTERN.test(currency)) {
    return null;
  }
  const departure = parseDateTime(raw.departure);
  if (departure === null) {
    return null;
  }
  const arrival = parseDateTime(raw.arrival);
  if (arrival === null) {
    return null;
  }
  const fares = readFares(raw.fares);
  if (fares.length === 0) {
    return null;
  }
  return {
    flightNumber,
    origin,
    destination,
    currency,
    departs: departure.time,
    arrives: arrival.time,
    nextDay: arrival.date > departure.date,
    durationMinutes: readDurationMinutes(raw.duration_minutes),
    fares,
  };
}

export function readFlights(raw) {
  if (!Array.isArray(raw)) {
    return [];
  }
  return raw.map(readFlight).filter((flight) => flight !== null);
}

export function readFlightsNote(raw) {
  return typeof raw === "string" && raw.trim() !== "" ? raw : null;
}

export function formatDuration(minutes) {
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  if (hours === 0) {
    return `${remainder}m`;
  }
  if (remainder === 0) {
    return `${hours}h`;
  }
  return `${hours}h ${remainder}m`;
}

export function formatFare(cabin, amount, currency) {
  return `${CABIN_LABELS[cabin]} · ${currency} ${new Intl.NumberFormat("en-US").format(amount)}`;
}
