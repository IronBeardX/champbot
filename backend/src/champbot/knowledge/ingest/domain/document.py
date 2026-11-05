import re
from dataclasses import dataclass
from datetime import date

from champbot.common.core.domain.exceptions import ChampBotError

SLUG_PATTERN = re.compile(r"^[a-z0-9-]+$")
REQUIRED_FRONT_MATTER_KEYS = ("title", "source_url", "retrieved_at")


class InvalidPolicyDocumentError(ChampBotError):
    def __init__(self, slug: str, reason: str) -> None:
        super().__init__(f"Invalid policy document '{slug}': {reason}")
        self.slug = slug
        self.reason = reason


@dataclass(frozen=True)
class PolicyDocument:
    slug: str
    title: str
    source_url: str
    retrieved_at: date
    body: str


def parse_policy_document(slug: str, raw: str) -> PolicyDocument:
    if not SLUG_PATTERN.match(slug):
        raise InvalidPolicyDocumentError(slug, f"slug must match {SLUG_PATTERN.pattern}")

    front_matter, body = _split_front_matter(slug, raw)
    values = _parse_front_matter(slug, front_matter)

    try:
        retrieved_at = date.fromisoformat(values["retrieved_at"])
    except ValueError as error:
        raise InvalidPolicyDocumentError(slug, "retrieved_at must be an ISO date") from error

    return PolicyDocument(
        slug=slug,
        title=values["title"],
        source_url=values["source_url"],
        retrieved_at=retrieved_at,
        body=body.strip("\n"),
    )


def _split_front_matter(slug: str, raw: str) -> tuple[str, str]:
    lines = raw.splitlines()
    if not lines or lines[0].strip() != "---":
        raise InvalidPolicyDocumentError(slug, "must start with a '---' front matter block")

    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            front_matter = "\n".join(lines[1:index])
            body = "\n".join(lines[index + 1 :])
            return front_matter, body

    raise InvalidPolicyDocumentError(slug, "front matter block is not closed with '---'")


def _parse_front_matter(slug: str, front_matter: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in front_matter.splitlines():
        if not line.strip():
            continue
        key, separator, value = line.partition(":")
        if not separator:
            raise InvalidPolicyDocumentError(slug, f"malformed front matter line: {line!r}")
        values[key.strip()] = value.strip()

    missing = [key for key in REQUIRED_FRONT_MATTER_KEYS if not values.get(key)]
    if missing:
        raise InvalidPolicyDocumentError(slug, f"missing front matter keys: {missing}")

    return values
