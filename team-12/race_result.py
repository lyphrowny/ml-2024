from datetime import date
from collections.abc import Collection

import attrs


@attrs.define
class RaceResult:
    full_typ: tuple[str, int]
    full_date: tuple[date, int]
    full_participants: Collection[tuple[str, int]]

    @property
    def typ(self):
        return self.full_typ[0]

    @property
    def date(self):
        return self.full_date[0]

    @property
    def participants(self):
        return [p[0] for p in self.full_participants]
