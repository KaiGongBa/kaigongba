from __future__ import annotations

import re


# Browser acceptance runs use one correlation id for the buyer, provider,
# reviewer and platform accounts.  Keep the pattern deliberately narrow so a
# normal account containing words such as "buyer" is never classified as test
# data.
_AUTOMATED_ACCEPTANCE_USERNAME = re.compile(
    r"^[0-9a-f]{16}_(?:buyer|provider|reviewer|platform)$",
    re.IGNORECASE,
)


def is_automated_acceptance_username(username: str) -> bool:
    return bool(_AUTOMATED_ACCEPTANCE_USERNAME.fullmatch(username.strip()))
