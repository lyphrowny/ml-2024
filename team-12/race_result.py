from datetime import date
from collections.abc import Collection

import attrs


@attrs.define
class RaceResult:
    typ: str
    date: date
    participants: Collection[str]
