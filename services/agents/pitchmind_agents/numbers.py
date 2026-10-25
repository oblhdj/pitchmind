"""Locale-aware number extraction for the Verifier.

Agents write numbers the way their language does: ``0,38`` in French, ``68 %``,
Arabic-Indic digits, thin spaces between digit groups, and sometimes words
("quatre fois sur dix", "forty-seven"). The Verifier reads every one of them back to
a float and checks it against the supplied facts.

Number words are read in the segment's language and in English (drafts start in English).
Number words meaning one ("one", "un", "first", ...) are skipped on their own: they are
articles or ordinary words far more often than quantities.
"""

from __future__ import annotations

import itertools
import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from pitchmind_contracts import Language

_DIGITS = str.maketrans(
    "".join(chr(0x0660 + d) for d in range(10)) + "".join(chr(0x06F0 + d) for d in range(10)), "0123456789" * 2
)
# Arabic decimal and thousands separators.
_ARABIC_SEPARATORS = str.maketrans({chr(0x066B): ".", chr(0x066C): ","})
# French and Spanish put (narrow) no-break spaces between groups of three digits.
_GROUP_SPACES = "".join(map(chr, (0x00A0, 0x202F, 0x2009)))
_GROUP_SPACE = re.compile(rf"(?<=\d)[{_GROUP_SPACES}](?=\d{{3}}(?!\d))")
_NUMBER = re.compile(r"(?<![\d.,])\d+(?:[.,]\d+)*")
# Player ids (H10, A9) are identifiers, not quantities.
_PLAYER_ID = re.compile(r"\b[HA]\d{1,2}\b")
# Phrases that name rather than count: the halves ("second half", "2e mi-temps", "segundo tiempo",
# "الشوط الثاني") and "both" ("les deux équipes", "los dos equipos", "the two sides").
_NOT_COUNTS = re.compile(
    r"\b(?:1st|2nd|first|second)[\s-]+half\b"
    r"|\b(?:1re|1ère|2e|2nde|2ème|premi[eè]re|seconde|deuxi[eè]me)\s+mi-temps\b"
    r"|\b(?:1er|1o|2o|primer|segundo)\s+tiempo\b|\b(?:primera|segunda)\s+parte\b"
    r"|الشوط\s+(?:الأول|الثاني)"
    r"|\b(?:les\s+deux|los\s+dos|las\s+dos|the\s+two)\b",
    re.IGNORECASE,
)
_WORD = re.compile(r"[^\W\d_]+(?:-[^\W\d_]+)*")
# Alef with hamza or madda is often written as a bare alef.
_ALEF = str.maketrans({chr(0x0623): chr(0x0627), chr(0x0625): chr(0x0627), chr(0x0622): chr(0x0627)})
_IGNORED_WORDS = frozenset({"one-two", "one-twos"})  # the passing move


@dataclass(frozen=True, slots=True)
class Reading:
    value: float
    decimals: int


@dataclass(frozen=True, slots=True)
class NumberToken:
    raw: str
    readings: tuple[Reading, ...]


def _words(spec: str) -> dict[str, int]:
    """``"two 2 three 3"`` -> ``{"two": 2, "three": 3}``, with Arabic alef variants folded."""
    parts = spec.split()
    return {word.translate(_ALEF): int(value) for word, value in itertools.batched(parts, 2)}


@dataclass(frozen=True, slots=True)
class _Lexicon:
    words: Mapping[str, int]
    compound_only: Mapping[str, int] = field(default_factory=dict)  # "one", "un": only inside "twenty-one"
    connectors: frozenset[str] = frozenset()  # "y" in "treinta y cinco", "et" in "vingt et un"
    prefixes: tuple[str, ...] = ()  # Arabic "و" (and) glued to the next word

    def get(self, word: str) -> tuple[int, bool] | None:
        """(value, usable on its own) for a lower-cased word, or None."""
        for candidate in (word, *(word[len(p) :] for p in self.prefixes if word.startswith(p) and len(word) > 2)):
            if candidate in self.words:
                return self.words[candidate], True
            if candidate in self.compound_only:
                return self.compound_only[candidate], False
        return None


_LEXICONS: dict[Language, _Lexicon] = {
    Language.EN: _Lexicon(
        words=_words("""
            zero 0 nil 0 two 2 three 3 four 4 five 5 six 6 seven 7 eight 8 nine 9 ten 10 eleven 11 twelve 12
            thirteen 13 fourteen 14 fifteen 15 sixteen 16 seventeen 17 eighteen 18 nineteen 19 twenty 20
            thirty 30 forty 40 fifty 50 sixty 60 seventy 70 eighty 80 ninety 90 hundred 100 twice 2 dozen 12
            second 2 third 3 fourth 4 fifth 5 sixth 6 seventh 7 eighth 8 ninth 9 tenth 10 eleventh 11
            twelfth 12 thirteenth 13 fourteenth 14 fifteenth 15 sixteenth 16 seventeenth 17 eighteenth 18
            nineteenth 19 twentieth 20 thirtieth 30 fortieth 40 fiftieth 50 sixtieth 60 seventieth 70
            eightieth 80 ninetieth 90 hundredth 100
        """),
        compound_only=_words("one 1 first 1"),
    ),
    Language.FR: _Lexicon(
        words=_words("""
            zéro 0 deux 2 trois 3 quatre 4 cinq 5 six 6 sept 7 huit 8 neuf 9 dix 10 onze 11 douze 12 treize 13
            quatorze 14 quinze 15 seize 16 vingt 20 vingts 20 trente 30 quarante 40 cinquante 50 soixante 60
            septante 70 huitante 80 nonante 90 quatre-vingt 80 quatre-vingts 80 cent 100 deuxième 2
            troisième 3 quatrième 4 cinquième 5 sixième 6 septième 7 huitième 8 neuvième 9 dixième 10
            onzième 11 douzième 12 treizième 13 quatorzième 14 quinzième 15 seizième 16 vingtième 20
            trentième 30 quarantième 40 cinquantième 50 soixantième 60 centième 100
        """),
        compound_only=_words("un 1 une 1 unième 1 premier 1 première 1"),
        connectors=frozenset({"et"}),
    ),
    Language.ES: _Lexicon(
        words=_words("""
            cero 0 dos 2 tres 3 cuatro 4 cinco 5 seis 6 siete 7 ocho 8 nueve 9 diez 10 once 11 doce 12 trece 13
            catorce 14 quince 15 dieciséis 16 diecisiete 17 dieciocho 18 diecinueve 19 veinte 20 veintiuno 21
            veintiún 21 veintiuna 21 veintidós 22 veintitrés 23 veinticuatro 24 veinticinco 25 veintiséis 26
            veintisiete 27 veintiocho 28 veintinueve 29 treinta 30 cuarenta 40 cincuenta 50 sesenta 60
            setenta 70 ochenta 80 noventa 90 cien 100 ciento 100 segundo 2 segunda 2 tercero 3 tercer 3
            tercera 3 quinto 5 sexto 6 séptimo 7 octavo 8 noveno 9 décimo 10
        """),
        compound_only=_words("uno 1 una 1 un 1 primer 1 primero 1 primera 1"),
        connectors=frozenset({"y"}),
    ),
    Language.AR: _Lexicon(
        words=_words("""
            صفر 0 اثنان 2 اثنين 2 اثنتان 2 اثنتين 2 مرتين 2 مرتان 2 ثلاثة 3 ثلاث 3 أربعة 4 أربع 4 خمسة 5 خمس 5
            ستة 6 ست 6 سبعة 7 سبع 7 ثمانية 8 ثماني 8 ثمان 8 تسعة 9 تسع 9 عشرة 10 عشر 10 عشرون 20 عشرين 20
            ثلاثون 30 ثلاثين 30 أربعون 40 أربعين 40 خمسون 50 خمسين 50 ستون 60 ستين 60 سبعون 70 سبعين 70
            ثمانون 80 ثمانين 80 تسعون 90 تسعين 90 مئة 100 مائة 100 الثاني 2 الثانية 2 الثالث 3 الثالثة 3
            الرابع 4 الرابعة 4 الخامس 5 الخامسة 5 السادس 6 السادسة 6 السابع 7 السابعة 7 الثامن 8 الثامنة 8
            التاسع 9 التاسعة 9 العاشر 10 العاشرة 10
        """),
        compound_only=_words("واحد 1 واحدة 1 أحد 1 إحدى 1 الأول 1 الأولى 1 اثنا 2"),
        prefixes=("و",),
    ),
}
_ARABIC_TEN = frozenset({"عشر", "عشرة"})


def _with_english(lex: _Lexicon) -> _Lexicon:
    """Drafts start in English, so an untranslated "four times out of ten" must not slip through."""
    en = _LEXICONS[Language.EN]
    return _Lexicon(
        words={**en.words, **lex.words},
        compound_only={**en.compound_only, **lex.compound_only},
        connectors=en.connectors | lex.connectors,
        prefixes=lex.prefixes,
    )


_SCAN = {lang: lex if lang is Language.EN else _with_english(lex) for lang, lex in _LEXICONS.items()}


def _readings(raw: str) -> tuple[Reading, ...]:
    """Every plausible value of ``raw``: ``1,234`` may be 1234 (EN) or 1.234 (FR)."""
    groups = re.split(r"[.,]", raw)
    seps = re.findall(r"[.,]", raw)
    if not seps:
        return (Reading(float(raw), 0),)
    out: list[Reading] = []
    if (
        len(set(seps)) == 1
        and 1 <= len(groups[0]) <= 3
        and not groups[0].startswith("0")  # "0.123" is never a thousands group
        and all(len(g) == 3 for g in groups[1:])
    ):
        out.append(Reading(float("".join(groups)), 0))
    *head, tail = groups
    head_seps = seps[:-1]
    if (
        len(set(head_seps)) <= 1
        and (not head_seps or head_seps[0] != seps[-1])
        and (not head_seps or (1 <= len(head[0]) <= 3 and all(len(g) == 3 for g in head[1:])))
    ):
        out.append(Reading(float("".join(head) + "." + tail), len(tail)))
    return tuple(out)


def normalize(text: str) -> str:
    text = text.translate(_DIGITS).translate(_ARABIC_SEPARATORS)
    return _GROUP_SPACE.sub("", text)


def _digit_tokens(text: str) -> list[NumberToken]:
    ids = [m.span() for m in _PLAYER_ID.finditer(text)]
    tokens: list[NumberToken] = []
    for m in _NUMBER.finditer(text):
        if any(start <= m.start() and m.end() <= end for start, end in ids):
            continue
        raw = m.group()
        readings = _readings(raw)
        if readings:
            tokens.append(NumberToken(raw, readings))
        else:  # a list such as "9,27,33"
            tokens.extend(NumberToken(g, (Reading(float(g), 0),)) for g in re.split(r"[.,]", raw))
    return tokens


def _compound(word: str, lex: _Lexicon) -> tuple[int, bool] | None:
    """A whole (possibly hyphenated) word: "twenty-five", "quatre-vingt-dix", "vingt-et-un"."""
    parts = [p for p in word.split("-") if p not in lex.connectors]
    merged: list[str] = []
    while parts:
        if len(parts) > 1 and f"{parts[0]}-{parts[1]}" in lex.words:
            merged.append(f"{parts.pop(0)}-{parts.pop(0)}")
        else:
            merged.append(parts.pop(0))
    hits = [lex.get(p) for p in merged]
    if not hits or any(h is None for h in hits):
        return None
    values = [h[0] for h in hits if h is not None]
    if len(values) == 1:
        return hits[0]
    if all(a > b for a, b in itertools.pairwise(values)):  # tens then units
        return sum(values), True
    return None


def _joined(
    words: list[re.Match[str]], i: int, value: int, lex: _Lexicon, language: Language
) -> tuple[int, int] | None:
    """Multi-word numbers starting at ``words[i]``: (index of the last word, value)."""
    if 20 <= value <= 90 and value % 10 == 0 and i + 2 < len(words) and words[i + 1].group().lower() in lex.connectors:
        unit = _compound(words[i + 2].group().lower(), lex)
        if unit is not None and 1 <= unit[0] <= 19:
            return i + 2, value + unit[0]  # treinta y cinco, soixante et onze
    if language is Language.AR and 1 <= value <= 9 and i + 1 < len(words):
        nxt = words[i + 1].group().translate(_ALEF)
        if nxt in _ARABIC_TEN:
            return i + 1, value + 10  # ثلاثة عشر
        tens = lex.words.get(nxt[1:]) if nxt.startswith("و") else None
        if tens is not None and 20 <= tens <= 90 and tens % 10 == 0:
            return i + 1, value + tens  # خمسة وعشرون
    return None


def _word_tokens(text: str, language: Language) -> list[NumberToken]:
    lex = _SCAN[language]
    words = list(_WORD.finditer(text))
    tokens: list[NumberToken] = []
    i = 0
    while i < len(words):
        word = words[i].group().lower().translate(_ALEF)
        found = None if word in _IGNORED_WORDS else _compound(word, lex)
        if found is not None:
            joined = _joined(words, i, found[0], lex, language)
            if joined is not None:
                end, value = joined
                raw = text[words[i].start() : words[end].end()]
                tokens.append(NumberToken(raw, (Reading(float(value), 0),)))
                i = end + 1
                continue
            if found[1]:
                tokens.append(NumberToken(words[i].group(), (Reading(float(found[0]), 0),)))
        elif "-" in word and word not in _IGNORED_WORDS:
            for part in word.split("-"):  # "two-goal lead"
                hit = lex.get(part)
                if hit is not None and hit[1]:
                    tokens.append(NumberToken(part, (Reading(float(hit[0]), 0),)))
        i += 1
    return tokens


def extract_numbers(text: str, language: Language = Language.EN) -> list[NumberToken]:
    """Digits in any locale, plus number words in ``language``. Halves and "both" are left out."""
    text = _NOT_COUNTS.sub(" ", normalize(text))
    return _digit_tokens(text) + _word_tokens(text, language)


def numbers_in(text: str) -> set[float]:
    """Values written as digits in a deterministic sentence or a name (no number words)."""
    return {r.value for token in _digit_tokens(normalize(text)) for r in token.readings}


def is_supported(token: NumberToken, allowed: Iterable[float]) -> bool:
    """True when the token states an allowed value, exactly or rounded to the precision it shows.

    Signs are ignored (``-0.35`` is written as "from -0.35" or "0.35 below"). A whole number may
    round a fact only when the fact is at least 10, so ``1`` never stands in for ``0.71``.
    """
    facts = [abs(a) for a in allowed]
    for reading in token.readings:
        for fact in facts:
            if math.isclose(reading.value, fact, abs_tol=1e-9):
                return True
            if (reading.decimals > 0 or fact >= 10) and math.isclose(
                round(fact, reading.decimals), reading.value, abs_tol=10 ** -(reading.decimals + 3)
            ):
                return True
    return False


def unsupported_numbers(text: str, allowed: Iterable[float], language: Language = Language.EN) -> list[str]:
    facts = list(allowed)
    return [token.raw for token in extract_numbers(text, language) if not is_supported(token, facts)]
