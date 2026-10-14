"""Tuplets, and the sounded duration they produce.

`Entry.duration` is the *written* duration. Inside a tuplet the note sounds for a
different length, so anything that cares about time -- playback, MusicXML export,
checking that a measure adds up -- needs the ratio applied.

A tuplet is defined on the entry that *starts* it and covers a span of written
time from there, so scaling one entry means knowing which tuplets are in force at
it, which means walking the entry chain.

**Container-agnostic by construction.** The chain walk and the arithmetic work on
a plain `EntryChain`, which either container can build: `.musx` from its entries
pool, `.mus` from `read_mus_entries` plus the prev/next links in its slot headers.
Only `tuplets_by_entry` is `.musx`-specific, because the tuplet definitions live in
the `details` pool, which is not yet readable from `.mus`. When it is, `.mus` gets
tuplet scaling by supplying that one mapping -- nothing here changes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass
from fractions import Fraction

from finale_file_parser.enigma.document import EnigmaDocument, Record
from finale_file_parser.enigma.models import CorruptScoreError

__all__ = [
    "EntryChain",
    "entry_chain",
    "Tuplet",
    "read_tuplet",
    "sounded_durations",
    "tuplets_by_entry",
]

_TUPLET_TAG = "tupletDef"


def _scalar(record: Record, name: str) -> str | None:
    """A field's scalar text, or None if absent.

    `Record.fields` values may be nested records or repeated tuples; a field that
    should be a number but is not gets treated as missing so the caller raises a
    clear error rather than a TypeError from deep inside int().
    """
    value = record.fields.get(name)
    return value if isinstance(value, str) else None


@dataclass(frozen=True)
class Tuplet:
    """A tuplet: `symbolic` notes played in the time of `reference` notes.

    A triplet of eighths is symbolic 3x512 in the time of reference 2x512.
    """

    symbolic_number: int
    symbolic_duration: int
    reference_number: int
    reference_duration: int

    @property
    def ratio(self) -> Fraction:
        """Multiply a written duration by this to get the sounded duration."""
        return Fraction(
            self.reference_number * self.reference_duration,
            self.symbolic_number * self.symbolic_duration,
        )

    @property
    def span(self) -> int:
        """Written EDU the tuplet covers, starting at the entry it is defined on."""
        return self.symbolic_number * self.symbolic_duration

    @property
    def reference_total(self) -> int:
        """Written EDU of the time the tuplet occupies: 2 x 512 for an eighth triplet."""
        return self.reference_number * self.reference_duration


@dataclass(frozen=True)
class EntryChain:
    """Entries in playing order, with their written durations.

    The seam that keeps this container-agnostic: both `.musx` and `.mus` can
    produce one, and everything below works on it alone.
    """

    order: Sequence[int]
    """Entry numbers, in the order they are played."""

    written_edu: Mapping[int, int]
    """Entry number -> written duration in EDU."""

    grace_notes: Set[int] = frozenset()
    """Entries that are grace notes.

    A grace note carries a written duration but sounds for no time, so it neither
    contributes to a measure's total nor consumes any of a tuplet's span. Treating
    one as ordinary makes its measure overflow -- the effect is not subtle: four
    grace notes push a 4/4 measure to 6144 EDU against a capacity of 4096.
    """


def read_tuplet(record: Record) -> Tuplet:
    """Read a `tupletDef` record.

    **`refNum` may be zero**: "one 64th in the time of none". Its notes then
    sound for no time at all, which is what the score means by it -- in the one
    document that carries such tuplets (two, each on a 64th inserted into a run
    of 64ths), both staves of the measure sum to exactly their 3/4 with the
    inserted notes at zero and overflow by 64 EDU with the tuplet ignored. Every
    other field is a divisor or a span and must stay positive.

    Raises:
        CorruptScoreError: a required field is missing or not an integer, a
            field other than `refNum` is not positive, or `refNum` is negative.
    """

    def field(name: str, *, smallest_allowed: int = 1) -> int:
        raw = _scalar(record, name)
        if raw is None:
            raise CorruptScoreError(f"tupletDef is missing {name!r}")
        try:
            value = int(raw)
        except ValueError as exc:
            raise CorruptScoreError(f"tupletDef {name}={raw!r} is not an integer") from exc
        if value < smallest_allowed:
            raise CorruptScoreError(f"tupletDef {name}={value} must be at least {smallest_allowed}")
        return value

    return Tuplet(
        symbolic_number=field("symbolicNum"),
        symbolic_duration=field("symbolicDur"),
        reference_number=field("refNum", smallest_allowed=0),
        reference_duration=field("refDur"),
    )


def tuplets_by_entry(document: EnigmaDocument) -> dict[int, tuple[Tuplet, ...]]:
    """Every tuplet, grouped by the entry that starts it.

    An entry can start more than one (nested tuplets), which is why the value is a
    tuple rather than a single tuplet.

    **Score records only.** A linked part can override a tuplet, and what it
    stores is only what it overrides: all 12 in the corpus are `shared="true"`
    and carry bracket-hook geometry and nothing else -- no ratio at all, because
    the score record already has it. Reading one as a definition raised on the
    missing `symbolicNum` and cost three documents. Reading one that *did* carry
    a ratio would be the worse failure: an entry's tuplets are a tuple, so the
    override would arrive as a second, nested tuplet and silently rescale the
    music. Every other pool reader in this package filters part variants the same
    way, and this one simply did not.
    """
    out: dict[int, list[Tuplet]] = {}
    for record in document.details.records:
        if record.tag != _TUPLET_TAG or "part" in record.attrs:
            continue
        raw = record.attrs.get("entnum")
        if raw is None:
            raise CorruptScoreError("tupletDef has no entnum")
        out.setdefault(int(raw), []).append(read_tuplet(record))
    return {entnum: tuple(items) for entnum, items in out.items()}


def sounded_durations(
    chain: EntryChain,
    tuplets: Mapping[int, Sequence[Tuplet]],
) -> dict[int, Fraction]:
    """Sounded duration in EDU for every entry in `chain`.

    Zero for a grace note. Otherwise the written duration times the ratio of
    every tuplet in force, since nested tuplets multiply.

    **A tuplet's span is consumed at its own nesting level.** An entry's written
    duration counts only against the innermost tuplet in force; when that one
    completes, the tuplet enclosing it consumes the inner one's *reference*
    duration. A 16th triplet inside an eighth triplet therefore uses up one
    eighth of the outer span, not the three 16ths it writes. Counting written
    time against every level ran the outer triplet on past its notes: in
    *Undertale - Mysterious Place* every measure of two staves sounded 5,746 EDU
    against a 4,096-EDU bar.

    The rest follows the musx object model's `createEntryFrame`
    (https://github.com/rpatters1/musx-object-model/blob/deda69c1a8622c4268000f8c3e8df460ddef41a8/src/musx/dom/Entries.cpp#L2547-L2720):

    * tuplets starting on the same entry open longest display duration first,
      then longest reference duration, so the enclosing one is outermost;
    * a tuplet also completes once the time sounded inside it reaches its
      reference duration scaled by every enclosing ratio;
    * the entry that completes a tuplet ends exactly where the tuplet does, so
      rounding or an uneven fill inside one cannot drift the rest of the chain.
    """
    open_tuplets: list[_OpenTuplet] = []
    out: dict[int, Fraction] = {}
    elapsed = Fraction(0)

    for entnum in chain.order:
        written = chain.written_edu.get(entnum)
        if written is None:
            raise CorruptScoreError(f"entry {entnum} has no written duration")
        if entnum in chain.grace_notes:
            out[entnum] = Fraction(0)
            continue
        starting_here = sorted(
            tuplets.get(entnum, ()),
            key=lambda tuplet: (tuplet.span, tuplet.reference_total),
            reverse=True,
        )
        for tuplet in starting_here:
            enclosing_ratio = _product_of_ratios(open_tuplets)
            open_tuplets.append(
                _OpenTuplet(
                    tuplet=tuplet,
                    starts_at=elapsed,
                    sounds_for=tuplet.reference_total * enclosing_ratio,
                )
            )

        sounded = written * _product_of_ratios(open_tuplets)
        ends_at = elapsed + sounded
        if open_tuplets:
            for open_tuplet in open_tuplets:
                open_tuplet.sounded_inside += sounded
            open_tuplets[-1].written_consumed += written
            while open_tuplets and open_tuplets[-1].is_complete:
                completed = open_tuplets.pop()
                ends_at = completed.starts_at + completed.sounds_for
                if open_tuplets:
                    open_tuplets[-1].written_consumed += completed.tuplet.reference_total
            ends_at = max(ends_at, elapsed)
        out[entnum] = ends_at - elapsed
        elapsed = ends_at
    return out


@dataclass
class _OpenTuplet:
    tuplet: Tuplet
    starts_at: Fraction
    sounds_for: Fraction
    written_consumed: int = 0
    sounded_inside: Fraction = Fraction(0)

    @property
    def is_complete(self) -> bool:
        return self.written_consumed >= self.tuplet.span or self.sounded_inside >= self.sounds_for


def _product_of_ratios(open_tuplets: Sequence[_OpenTuplet]) -> Fraction:
    product = Fraction(1)
    for open_tuplet in open_tuplets:
        product *= open_tuplet.tuplet.ratio
    return product


def entry_chain(document: EnigmaDocument) -> EntryChain:
    """Build an `EntryChain` from a `.musx` document.

    The `.musx` adapter for the seam above. Entries form doubly-linked chains via
    their `prev`/`next` attributes -- one chain per frame -- so order is recovered
    by starting at each head (`prev == 0`) and following `next`.

    Chain order is used rather than document order because a tuplet's extent is
    measured in played time; reading records in file order would silently
    mis-assign spans wherever the two differ.
    """
    following: dict[int, int] = {}
    written: dict[int, int] = {}
    grace: set[int] = set()
    heads: list[int] = []
    for record in document.entries.records:
        entnum = int(record.attrs["entnum"])
        if "graceNote" in record.fields:
            grace.add(entnum)
        raw_duration = _scalar(record, "dura")
        if raw_duration is None:
            raise CorruptScoreError(f"entry {entnum} has no dura")
        written[entnum] = int(raw_duration)
        following[entnum] = int(record.attrs.get("next", 0) or 0)
        if not int(record.attrs.get("prev", 0) or 0):
            heads.append(entnum)

    order: list[int] = []
    seen: set[int] = set()
    for head in heads:
        entnum = head
        while entnum and entnum in written and entnum not in seen:
            seen.add(entnum)
            order.append(entnum)
            entnum = following.get(entnum, 0)
    # Any entry not reachable from a head still needs a duration reported; a
    # broken link must not silently drop notes.
    order.extend(entnum for entnum in written if entnum not in seen)
    return EntryChain(order=order, written_edu=written, grace_notes=frozenset(grace))
