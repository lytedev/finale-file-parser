"""Events that sound for no time reach MusicXML as grace notes, with no tuplet ratio.

Two things in Finale take no metric time: a grace note, and a note inside a
tuplet of "n in the time of none" (`refNum` 0). MusicXML can say this only one
way -- `<grace/>` and no `<duration>` -- and a `<time-modification>` of "1 in the
time of 0" next to it is a ratio no reader can scale by.
"""

from __future__ import annotations

from fractions import Fraction

from defusedxml import ElementTree as DET

from finale_file_parser.enigma.document import parse_enigma
from finale_file_parser.enigma.to_ir import build_score
from finale_file_parser.export.musicxml import to_musicxml
from finale_file_parser.ir import Event, Score

NS = "http://www.makemusic.com/2012/finale"

_SIXTY_FOURTH_IN_THE_TIME_OF_NONE = """
      <tupletDef entnum="3">
        <symbolicNum>1</symbolicNum><symbolicDur>64</symbolicDur>
        <refNum>0</refNum><refDur>64</refDur>
      </tupletDef>"""


def _entry(number: int, count: int, edu: int, *, grace: bool = False) -> str:
    next_number = number + 1 if number < count else 0
    grace_field = "<graceNote/>" if grace else ""
    return (
        f'<entry entnum="{number}" prev="{number - 1}" next="{next_number}">'
        f"<numNotes>1</numNotes><dura>{edu}</dura><isNote/>{grace_field}"
        '<note id="1"><harmLev>0</harmLev><harmAlt>0</harmAlt></note></entry>'
    )


def _four_four_measure(entries: str, count: int, details: str = "") -> bytes:
    return f"""<finale version="18.0" xmlns="{NS}">
    <entries>{entries}</entries>
    <others>
      <frameSpec cmper="10" inci="0">
        <startEntry>1</startEntry><endEntry>{count}</endEntry>
      </frameSpec>
      <measSpec cmper="1">
        <keySig><key>0</key></keySig><beats>4</beats><divbeat>1024</divbeat>
      </measSpec>
      <staffSpec cmper="1"><x>a</x></staffSpec>
    </others>
    <details><gfhold cmper1="1" cmper2="1"><frame1>10</frame1></gfhold>{details}</details>
</finale>""".encode()


QUARTERS_WITH_A_SIXTY_FOURTH_IN_THE_TIME_OF_NONE = _four_four_measure(
    _entry(1, 5, 1024)
    + _entry(2, 5, 1024)
    + _entry(3, 5, 64)
    + _entry(4, 5, 1024)
    + _entry(5, 5, 1024),
    count=5,
    details=_SIXTY_FOURTH_IN_THE_TIME_OF_NONE,
)

A_GRACE_NOTE_BEFORE_FOUR_QUARTERS = _four_four_measure(
    _entry(1, 5, 512, grace=True)
    + _entry(2, 5, 1024)
    + _entry(3, 5, 1024)
    + _entry(4, 5, 1024)
    + _entry(5, 5, 1024),
    count=5,
)


def _events(score: Score) -> list[Event]:
    return [
        event
        for measure in score.parts[0].measures
        for voice in measure.voices
        for event in voice.events
    ]


def test_a_note_in_a_tuplet_of_none_sounds_for_no_time_and_leaves_its_measure_full() -> None:
    events = _events(build_score(parse_enigma(QUARTERS_WITH_A_SIXTY_FOURTH_IN_THE_TIME_OF_NONE)))
    inserted_sixty_fourth = events[2]
    measure_total = sum((event.duration for event in events), Fraction(0))

    assert inserted_sixty_fourth.duration == 0, (
        "one 64th in the time of no 64ths sounds for no time, but it sounded "
        f"{inserted_sixty_fourth.duration}"
    )
    assert measure_total == 1, (
        "four quarters fill the 4/4 measure and the 64th in the time of none adds nothing, "
        f"but the measure sums to {measure_total}"
    )


def test_a_note_in_a_tuplet_of_none_is_exported_as_a_grace_note() -> None:
    inserted_sixty_fourth = _events(
        build_score(parse_enigma(QUARTERS_WITH_A_SIXTY_FOURTH_IN_THE_TIME_OF_NONE))
    )[2]
    assert inserted_sixty_fourth.is_grace, (
        "MusicXML expresses a note that takes no time only as a grace note, and its schema "
        "rejects a zero <duration>"
    )
    assert inserted_sixty_fourth.tuplet_ratio is None, (
        f"a ratio of {inserted_sixty_fourth.tuplet_ratio} would export as '1 in the time of 0'"
    )


def test_a_grace_note_has_no_tuplet_ratio() -> None:
    grace_event = _events(build_score(parse_enigma(A_GRACE_NOTE_BEFORE_FOUR_QUARTERS)))[0]
    assert grace_event.is_grace and grace_event.tuplet_ratio is None, (
        "a grace note sounds for no time and is in no tuplet, so it must carry no ratio, "
        f"but it carried {grace_event.tuplet_ratio}"
    )


def test_a_grace_note_carries_no_time_modification() -> None:
    musicxml = to_musicxml(build_score(parse_enigma(A_GRACE_NOTE_BEFORE_FOUR_QUARTERS))).decode()
    grace_note = DET.fromstring(musicxml).find(".//note")
    assert grace_note is not None and grace_note.find("grace") is not None, (
        "the first note is flagged graceNote, so it must export with <grace/>"
    )
    assert grace_note.find("time-modification") is None, (
        "a grace note is not in a tuplet; a <time-modification> on it claims "
        "'1 in the time of 0', which no reader can scale by"
    )
