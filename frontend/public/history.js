export const MAX_USER_TEXT_LENGTH = 2000;
export const MAX_ASSISTANT_TEXT_LENGTH = 8000;
export const MAX_HISTORY_ITEMS = 20;
export const MAX_HISTORY_TEXT_LENGTH = 40_000;

function codePointLength(text) {
  return [...text].length;
}

function isBlank(text) {
  return text.trim() === "";
}

function fitsAlone(pair) {
  return (
    !isBlank(pair.user) &&
    !isBlank(pair.assistant) &&
    codePointLength(pair.user) <= MAX_USER_TEXT_LENGTH &&
    codePointLength(pair.assistant) <= MAX_ASSISTANT_TEXT_LENGTH
  );
}

export function buildHistory(pairs) {
  const eligible = pairs.filter(fitsAlone);

  const kept = [];
  let itemCount = 0;
  let charTotal = 0;
  for (let index = eligible.length - 1; index >= 0; index -= 1) {
    const pair = eligible[index];
    const pairLength = codePointLength(pair.user) + codePointLength(pair.assistant);
    if (itemCount + 2 > MAX_HISTORY_ITEMS || charTotal + pairLength > MAX_HISTORY_TEXT_LENGTH) {
      break;
    }
    kept.unshift(pair);
    itemCount += 2;
    charTotal += pairLength;
  }

  return kept.flatMap((pair) => [
    { role: "user", text: pair.user },
    { role: "assistant", text: pair.assistant },
  ]);
}
