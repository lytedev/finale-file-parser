"""Composite time signatures: `beats`/`divbeat` naming `timeUpper`/`timeLower` records.

The shapes here are those of the one composite document in the NinSheetMusic
collection -- "3 dotted eighths + 1 quarter" and "2 dotted eighths + 1 quarter"
-- built synthetically.
"""

from __future__ import annotations

import pytest

from finale_file_parser.enigma import mus_document
from finale_file_parser.enigma.document import Record, parse_enigma
from finale_file_parser.enigma.models import CorruptScoreError
from finale_file_parser.enigma.timesig import (
    TimeSignature,
    read_time_signature,
    time_signatures,
)

NS = "http://www.makemusic.com/2012/finale"

DOTTED_EIGHTH_EDU = 768
QUARTER_EDU = 1024
SIXTEENTH_EDU = 256


def _document(others: str) -> bytes:
    return f'<finale version="18.0" xmlns="{NS}"><others>{others}</others></finale>'.encode()


def _composite_measure(beats_cmper: int, divbeat_cmper: int) -> str:
    return (
        f'<measSpec cmper="1"><beats>{beats_cmper}</beats><divbeat>{divbeat_cmper}</divbeat>'
        "<altNumTsig/><altDenTsig/></measSpec>"
    )


def _time_upper(cmper: int, *counts: int) -> str:
    items = "".join(f"<tudata><integer>{count}</integer><startGroup/></tudata>" for count in counts)
    return f'<timeUpper cmper="{cmper}">{items}</timeUpper>'


def _time_lower(cmper: int, *units: int) -> str:
    items = "".join(f"<tldata><integer>{unit}</integer><startGroup/></tldata>" for unit in units)
    return f'<timeLower cmper="{cmper}">{items}</timeLower>'


@pytest.mark.parametrize(
    ("dotted_eighths", "expected_numerator"),
    [(3, 13), (2, 10)],
)
def test_a_composite_measure_is_its_sum_over_the_common_unit(
    dotted_eighths: int, expected_numerator: int
) -> None:
    document = parse_enigma(
        _document(
            _composite_measure(beats_cmper=339, divbeat_cmper=337)
            + _time_upper(339, dotted_eighths, 1)
            + _time_lower(337, DOTTED_EIGHTH_EDU, QUARTER_EDU)
        )
    )
    signature = time_signatures(document)[1]
    expected_total_edu = dotted_eighths * DOTTED_EIGHTH_EDU + QUARTER_EDU

    assert signature == TimeSignature(beats=expected_numerator, division_edu=SIXTEENTH_EDU), (
        f"{dotted_eighths} dotted eighths + 1 quarter is {expected_total_edu} EDU, which is "
        f"{expected_numerator} sixteenths, but the signature read as {signature}"
    )
    assert str(signature) == f"{expected_numerator}/16", (
        f"the conventional spelling must be {expected_numerator}/16, but was {signature}"
    )
    assert signature.total_edu == expected_total_edu, (
        f"the measure must hold {expected_total_edu} EDU, but holds {signature.total_edu}"
    )


def test_items_of_one_group_add_their_counts_and_their_units() -> None:
    """One group of counts 2+1 over units 512+256 lasts 3 x 768 EDU."""
    document = parse_enigma(
        _document(
            _composite_measure(beats_cmper=5, divbeat_cmper=6)
            + '<timeUpper cmper="5"><tudata><integer>2</integer><startGroup/></tudata>'
            "<tudata><integer>1</integer></tudata></timeUpper>"
            '<timeLower cmper="6"><tldata><integer>512</integer><startGroup/></tldata>'
            "<tldata><integer>256</integer></tldata></timeLower>"
        )
    )
    signature = time_signatures(document)[1]
    assert signature.total_edu == 3 * 768, (
        "(2 + 1) counts of (512 + 256) EDU is 2304 EDU, "
        f"but the measure holds {signature.total_edu}"
    )


def test_a_composite_whose_halves_group_differently_is_refused() -> None:
    document = parse_enigma(
        _document(
            _composite_measure(beats_cmper=339, divbeat_cmper=337)
            + _time_upper(339, 3, 1)
            + _time_lower(337, DOTTED_EIGHTH_EDU)
        )
    )
    with pytest.raises(CorruptScoreError, match="2 count group"):
        time_signatures(document)


def test_a_composite_naming_a_missing_record_is_refused() -> None:
    document = parse_enigma(
        _document(_composite_measure(beats_cmper=339, divbeat_cmper=337) + _time_upper(339, 3, 1))
    )
    with pytest.raises(CorruptScoreError, match="missing timeLower 337"):
        time_signatures(document)


def test_reading_a_composite_measure_alone_is_refused_rather_than_misread() -> None:
    """Its beats and divbeat are record numbers: 339/337 read as counts is nonsense."""
    measure = parse_enigma(_document(_composite_measure(339, 337))).others.of_tag("measSpec")[0]
    with pytest.raises(CorruptScoreError, match="composite"):
        read_time_signature(measure)


def _meas_spec_payload(beats: int, divbeat: int, time_signature_flags: int) -> bytes:
    width_and_key = bytes(4)
    return (
        width_and_key
        + beats.to_bytes(2, "little")
        + divbeat.to_bytes(2, "little")
        + time_signature_flags.to_bytes(2, "little")
        + bytes(2)
    )


def test_a_mus_measure_with_both_composite_bits_is_marked_composite() -> None:
    fields = mus_document._meas_spec(_meas_spec_payload(339, 337, 0x00C6))
    assert "altNumTsig" in fields and "altDenTsig" in fields, (
        f"bits 0x40 and 0x80 at +8 mark a composite measure, but the fields were {fields}"
    )


def test_a_mus_measure_without_the_composite_bits_is_plain() -> None:
    fields = mus_document._meas_spec(_meas_spec_payload(4, 1024, 0x2006))
    assert "altNumTsig" not in fields and "altDenTsig" not in fields, (
        f"a measure without bits 0x40/0x80 at +8 is not composite, but the fields were {fields}"
    )


@pytest.mark.parametrize("lone_bit", [0x40, 0x80])
def test_a_mus_measure_with_only_one_composite_bit_is_refused(lone_bit: int) -> None:
    """The two bits never occur apart, so nothing says which half one alone means."""
    with pytest.raises(CorruptScoreError, match="only composite time signature bit"):
        mus_document._meas_spec(_meas_spec_payload(339, 337, lone_bit))


def _item_integers(items: object) -> list[object]:
    assert isinstance(items, tuple), f"composite items must be a tuple of records, not {items!r}"
    return [item.fields["integer"] for item in items if isinstance(item, Record)]


def test_mus_composite_records_decode_to_the_musx_shape() -> None:
    upper_payload = bytes.fromhex("0300 0000 0100 0100 0000 0100".replace(" ", ""))
    lower_payload = bytes.fromhex("0003 0100 0004 0100 0000 0000".replace(" ", ""))

    upper = mus_document._time_upper(upper_payload)
    lower = mus_document._time_lower(lower_payload)

    upper_counts = _item_integers(upper["tudata"])
    lower_units = _item_integers(lower["tldata"])
    assert upper_counts == ["3", "1"], (
        f"the 12-byte upper record holds two 6-byte items, 3 and 1, but read as {upper_counts}"
    )
    assert lower_units == ["768", "1024"], (
        "the 12-byte lower record holds two 4-byte items, 768 and 1024 EDU, and a zero "
        f"padding item, but read as {lower_units}"
    )
