export function remainingSeconds(deadlineMs, nowMs) {
  return Math.max(Math.ceil((deadlineMs - nowMs) / 1000), 0);
}

export function retryLabel(remaining) {
  return remaining === 0 ? "Retry" : `Retry in ${remaining} s`;
}
