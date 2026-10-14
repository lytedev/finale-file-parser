"""Time signatures.

Enigma does not store a numerator and denominator. It stores how many divisions a
measure has (`beats`) and how long each division is in EDU (`divbeat`), which is
how it represents compound meters naturally: 6/8 is two dotted-quarter divisions,
not six eighths. `TimeSignature` keeps that representation and derives the
conventional pair on request.

Every `measSpec` in the corpus carries both fields (2,622 of 2,622), so unlike the
key signature there is no inheritance to apply.

A **composite** measure (`altNumTsig`/`altDenTsig`) stores neither: its `beats`
and `divbeat` are the cmpers of a `timeUpper` and a `timeLower` record, which
list counts and units in groups -- "3 dotted eighths + 1 quarter". The IR has
one count and one unit per signature, so a composite is read as its sum over the
largest unit that divides every group: that one is 13/16. See
`composite_time_signature`.

A measure may also carry a *display* time signature -- what is printed, as opposed
to what the measure actually holds. It is only meaningful when `useDisplayTimesig`
is set; see `display_time_signature`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction

from finale_file_parser.enigma.document import EnigmaDocument, Record
from finale_file_parser.enigma.models import CorruptScoreError

__all__ = [
    "TimeSignature",
    "composite_time_signature",
    "display_time_signature",
    "read_time_signature",
    "time_signatures",
]

_WHOLE_EDU = 4096
_MEASURE_SPEC = "measSpec"
_DOTTED_FACTOR = 3
"""A dotted division is three of the next-smaller undotted unit."""


@dataclass(frozen=True)
class TimeSignature:
    """How a measure divides its time.

    `beats` divisions of `division_edu` each. 4/4 is 4 x 1024; 6/8 is 2 x 1536,
    because a dotted quarter is 1536 EDU.
    """

    beats: int
    division_edu: int

    @property
    def total_edu(self) -> int:
        """Written EDU the measure holds."""
        return self.beats * self.division_edu

    @property
    def is_compound(self) -> bool:
        """Does each division subdivide into three rather than two?"""
        return self.division_edu % _DOTTED_FACTOR == 0 and _is_power_of_two(
            self.division_edu // _DOTTED_FACTOR
        )

    @property
    def numerator(self) -> int:
        """Conventional numerator: 6 for 6/8, not 2."""
        return self.beats * _DOTTED_FACTOR if self.is_compound else self.beats

    @property
    def denominator(self) -> int:
        """Conventional denominator: 8 for 6/8."""
        unit = self.division_edu // _DOTTED_FACTOR if self.is_compound else self.division_edu
        if not _is_power_of_two(unit) or unit > _WHOLE_EDU:
            raise CorruptScoreError(
                f"division of {self.division_edu} EDU is not a notatable note value"
            )
        return _WHOLE_EDU // unit

    def __str__(self) -> str:
        return f"{self.numerator}/{self.denominator}"


def _is_power_of_two(value: int) -> bool:
    return value > 0 and value & (value - 1) == 0


def _positive_int(record: Record, name: str) -> int:
    raw = record.fields.get(name)
    if not isinstance(raw, str):
        raise CorruptScoreError(f"measSpec is missing {name!r}")
    try:
        value = int(raw)
    except ValueError as exc:
        raise CorruptScoreError(f"measSpec {name}={raw!r} is not an integer") from exc
    if value <= 0:
        raise CorruptScoreError(f"measSpec {name}={value} must be positive")
    return value


def read_time_signature(record: Record) -> TimeSignature:
    """The time signature a non-composite `measSpec` actually holds.

    Raises:
        CorruptScoreError: `beats` or `divbeat` is missing or not a positive
            integer, or the measure is composite -- its fields are then record
            numbers, which only `composite_time_signature` can follow.
    """
    if _is_composite(record):
        raise CorruptScoreError(
            "measSpec has a composite time signature; read it with composite_time_signature"
        )
    return TimeSignature(
        beats=_positive_int(record, "beats"),
        division_edu=_positive_int(record, "divbeat"),
    )


def display_time_signature(record: Record) -> TimeSignature | None:
    """The time signature *printed* on this measure, if it differs.

    Returns None unless the measure sets `useDisplayTimesig`. The `dispBeats` and
    `dispDivbeat` fields are present on every measure but hold a default when the
    flag is clear -- reading them unconditionally reports a display signature for
    1,937 of 2,622 corpus measures that do not have one, usually claiming 4/4 over
    a measure that is really 3/4.

    Raises:
        CorruptScoreError: the flag is set but the display fields are unusable.
    """
    if "useDisplayTimesig" not in record.fields:
        return None
    return TimeSignature(
        beats=_positive_int(record, "dispBeats"),
        division_edu=_positive_int(record, "dispDivbeat"),
    )


def time_signatures(document: EnigmaDocument) -> dict[int, TimeSignature]:
    """Every measure's time signature, keyed by measure number.

    Score records only; a linked-part `measSpec` would overwrite the score's.
    """
    out: dict[int, TimeSignature] = {}
    for record in document.others.of_tag(_MEASURE_SPEC):
        if "part" in record.attrs:
            continue
        raw = record.attrs.get("cmper")
        if raw is None:
            raise CorruptScoreError("measSpec has no cmper")
        out[int(raw)] = (
            composite_time_signature(record, document)
            if _is_composite(record)
            else read_time_signature(record)
        )
    return out


_COMPOSITE_FLAGS = ("altNumTsig", "altDenTsig")


def _is_composite(record: Record) -> bool:
    return any(flag in record.fields for flag in _COMPOSITE_FLAGS)


def composite_time_signature(record: Record, document: EnigmaDocument) -> TimeSignature:
    """A composite `measSpec`'s time signature, as one count of one unit.

    Each group pairs the counts of a `timeUpper` group with the units of the
    matching `timeLower` group and lasts (sum of counts) x (sum of units) -- the
    musx object model's reading, `TimeSignature::calcBeatValueAt` at
    https://github.com/rpatters1/musx-object-model/blob/deda69c1a8622c4268000f8c3e8df460ddef41a8/src/musx/dom/CommonClasses.cpp#L951-L972
    -- and the measure lasts the sum of its groups. That sum is expressed over
    the greatest common divisor of the groups' units, as `calcSimplified` does
    (same file, L911-L939): 3 x 768 + 1 x 1024 EDU is 13 x 256, so 13/16.

    Evidence: in the one composite `.mus` of the NinSheetMusic collection, all
    32 composite measures alternate 13/16 and 10/16 this way, and all 96 of their
    staff-measures (three staves, the reserved one included) hold exactly that
    much music once tuplets are applied.

    A half that is not composite contributes its plain `beats` or `divbeat` as a
    single group.

    Raises:
        CorruptScoreError: a referenced record is missing or empty, a count's
            fraction has a zero denominator, a unit is not positive, the halves
            have different numbers of groups, or the sum is not a whole number of
            the common unit.
    """
    count_groups = (
        _composite_groups(document, "timeUpper", "tudata", _positive_int(record, "beats"))
        if "altNumTsig" in record.fields
        else [[Fraction(_positive_int(record, "beats"))]]
    )
    unit_groups = (
        [
            [int(unit) for unit in group]
            for group in _composite_groups(
                document, "timeLower", "tldata", _positive_int(record, "divbeat")
            )
        ]
        if "altDenTsig" in record.fields
        else [[_positive_int(record, "divbeat")]]
    )
    if len(count_groups) != len(unit_groups):
        raise CorruptScoreError(
            f"composite time signature has {len(count_groups)} count group(s) "
            f"but {len(unit_groups)} unit group(s)"
        )
    unit_sums = [sum(units) for units in unit_groups]
    if any(unit_sum <= 0 for unit_sum in unit_sums):
        raise CorruptScoreError("composite time signature has a group with no positive unit")
    common_unit = math.gcd(*unit_sums)
    total_in_common_units = sum(
        (sum(counts, Fraction(0)) * (unit_sum // common_unit))
        for counts, unit_sum in zip(count_groups, unit_sums, strict=True)
    )
    if total_in_common_units.denominator != 1 or total_in_common_units <= 0:
        raise CorruptScoreError(
            f"composite time signature sums to {total_in_common_units} units of "
            f"{common_unit} EDU, not a positive whole number of them"
        )
    return TimeSignature(beats=int(total_in_common_units), division_edu=common_unit)


def _composite_groups(
    document: EnigmaDocument, tag: str, item_tag: str, cmper: int
) -> list[list[Fraction]]:
    """The items of one composite half, split where an item starts a group."""
    holder = document.others.get(tag, cmper)
    if holder is None:
        raise CorruptScoreError(f"composite time signature names missing {tag} {cmper}")
    raw_items = holder.fields.get(item_tag)
    items: tuple[Record, ...]
    if isinstance(raw_items, Record):
        items = (raw_items,)
    elif isinstance(raw_items, tuple):
        items = tuple(item for item in raw_items if isinstance(item, Record))
    else:
        items = ()
    if not items:
        raise CorruptScoreError(f"{tag} {cmper} holds no {item_tag} items")
    groups: list[list[Fraction]] = []
    for item in items:
        if "startGroup" in item.fields or not groups:
            groups.append([])
        groups[-1].append(_composite_item_value(item, tag, cmper))
    return groups


_FRACTION_NUMERATOR_SHIFT = 8
_FRACTION_DENOMINATOR_MASK = 0xFF


def _composite_item_value(item: Record, tag: str, cmper: int) -> Fraction:
    """An item's `integer`, plus a `frac` packed as numerator high byte, denominator low.

    The packing is the musx object model's reading of `<frac>`:
    https://github.com/rpatters1/musx-object-model/blob/deda69c1a8622c4268000f8c3e8df460ddef41a8/src/musx/factory/FieldPopulatorsOthers.cpp#L1662-L1665
    """
    raw_integer = item.fields.get("integer")
    if not isinstance(raw_integer, str):
        raise CorruptScoreError(f"{tag} {cmper} has an item with no integer")
    raw_fraction = item.fields.get("frac", "0")
    try:
        integer = int(raw_integer)
        packed_fraction = int(raw_fraction) if isinstance(raw_fraction, str) else 0
    except ValueError as exc:
        raise CorruptScoreError(f"{tag} {cmper} has a non-integer item") from exc
    if integer < 0 or packed_fraction < 0:
        raise CorruptScoreError(f"{tag} {cmper} has a negative item")
    numerator = packed_fraction >> _FRACTION_NUMERATOR_SHIFT
    denominator = packed_fraction & _FRACTION_DENOMINATOR_MASK
    if numerator and not denominator:
        raise CorruptScoreError(f"{tag} {cmper} has a fraction with a zero denominator")
    return Fraction(integer) + (Fraction(numerator, denominator) if numerator else Fraction(0))
