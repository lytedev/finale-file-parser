"""Hidden entries (`<ignore/>`, the `.mus` IGNOREBIT) reach the IR flagged, and draw no beam."""

from __future__ import annotations

from finale_file_parser.enigma.document import parse_enigma
from finale_file_parser.enigma.to_ir import build_score
from finale_file_parser.ir import Event, Score

NS = "http://www.makemusic.com/2012/finale"


def _eighth(number: int, count: int, *, hidden: bool = False, starts_beam: bool = False) -> str:
    next_number = number + 1 if number < count else 0
    extra = ("<ignore/>" if hidden else "") + ("<beam/>" if starts_beam else "")
    return (
        f'<entry entnum="{number}" prev="{number - 1}" next="{next_number}">'
        f"<numNotes>1</numNotes><dura>512</dura><isNote/>{extra}"
        '<note id="1"><harmLev>0</harmLev><harmAlt>0</harmAlt></note></entry>'
    )


def _two_four_measure(entries: str, count: int) -> bytes:
    return f"""<finale version="18.0" xmlns="{NS}">
    <entries>{entries}</entries>
    <others>
      <frameSpec cmper="10" inci="0">
        <startEntry>1</startEntry><endEntry>{count}</endEntry>
      </frameSpec>
      <measSpec cmper="1">
        <keySig><key>0</key></keySig><beats>2</beats><divbeat>1024</divbeat>
      </measSpec>
      <staffSpec cmper="1"><x>a</x></staffSpec>
    </others>
    <details><gfhold cmper1="1" cmper2="1"><frame1>10</frame1></gfhold></details>
</finale>""".encode()


def _events(score: Score) -> list[Event]:
    return [
        event
        for measure in score.parts[0].measures
        for voice in measure.voices
        for event in voice.events
    ]


FOUR_EIGHTHS_THE_LAST_HIDDEN = _two_four_measure(
    _eighth(1, 4, starts_beam=True) + _eighth(2, 4) + _eighth(3, 4) + _eighth(4, 4, hidden=True),
    count=4,
)

FOUR_EIGHTHS_THE_FIRST_HIDDEN_AND_STARTING_THE_GROUP = _two_four_measure(
    _eighth(1, 4, hidden=True, starts_beam=True) + _eighth(2, 4) + _eighth(3, 4) + _eighth(4, 4),
    count=4,
)


def test_a_hidden_entry_reaches_the_ir_flagged_and_keeps_its_time() -> None:
    events = _events(build_score(parse_enigma(FOUR_EIGHTHS_THE_LAST_HIDDEN)))
    hidden_flags = [event.is_hidden for event in events]
    assert hidden_flags == [False, False, False, True], (
        f"only the fourth eighth carries <ignore/>, but the hidden flags were {hidden_flags}"
    )
    assert events[3].duration == events[0].duration, (
        "a hidden entry still takes its time in the IR; only an exporter leaves it undrawn"
    )


def test_drawn_notes_beside_a_hidden_one_beam_among_themselves() -> None:
    events = _events(build_score(parse_enigma(FOUR_EIGHTHS_THE_LAST_HIDDEN)))
    primary_beams = [
        tuple(beam.type for beam in event.beams if beam.number == 1) for event in events
    ]
    assert primary_beams == [("begin",), ("continue",), ("end",), ()], (
        "a hidden eighth is not drawn, so the three drawn eighths must form a closed group "
        f"of their own, but the primary beams were {primary_beams}"
    )


def test_a_group_a_hidden_entry_starts_is_started_by_the_next_drawn_one() -> None:
    events = _events(
        build_score(parse_enigma(FOUR_EIGHTHS_THE_FIRST_HIDDEN_AND_STARTING_THE_GROUP))
    )
    primary_beams = [
        tuple(beam.type for beam in event.beams if beam.number == 1) for event in events
    ]
    assert primary_beams == [(), ("begin",), ("continue",), ("end",)], (
        "the hidden first eighth starts the group, so the first drawn eighth must begin it, "
        f"but the primary beams were {primary_beams}"
    )
