from datetime import date
from collections.abc import Collection

import attrs


@attrs.define
class RaceResult:
    full_typ: tuple(str, float)
    date: date
    full_participants: Collection[tuple(str, float)]

    @property
    def typ(self):
        return self.full_typ[0]

    @property
    def participants(self):
        return [p[0] for p in self.full_participants]
