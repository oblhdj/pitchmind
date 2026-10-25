import pytest
from pitchmind_agents.numbers import extract_numbers, is_supported, numbers_in, unsupported_numbers
from pitchmind_contracts import Language

NARROW_NBSP = chr(0x202F)
ARABIC_DECIMAL = chr(0x066B)
_TO_ARABIC_INDIC = str.maketrans("0123456789", "".join(chr(0x0660 + d) for d in range(10)))


def arabic_digits(text: str) -> str:
    return text.translate(_TO_ARABIC_INDIC)


def values(text: str) -> list[set[float]]:
    return [{r.value for r in token.readings} for token in extract_numbers(text)]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("xG of 0.38 at 104.2 km/h", [{0.38}, {104.2}]),
        ("L'indice est passé de 0,38 à 0,74", [{0.38}, {0.74}]),
        ("68 % de possession", [{68.0}]),
        (arabic_digits(f"مؤشر الضغط 0{ARABIC_DECIMAL}74 و 4 مرات"), [{0.74}, {4.0}]),
        (f"10{NARROW_NBSP}234 m parcourus", [{10234.0}]),
        ("1,234 m", [{1234.0, 1.234}]),
        ("10,234.5 m and 10.234,5 m", [{10234.5}, {10234.5}]),
        ("Haddad (H10) and A9 score", []),
        ("North City lead 2-1", [{2.0}, {1.0}]),
    ],
)
def test_extract_numbers_reads_every_locale(text: str, expected: list[set[float]]) -> None:
    assert values(text) == expected


def test_rounding_to_the_shown_precision_is_allowed_but_not_inventing_integers() -> None:
    (rounded,) = extract_numbers("104 km/h")
    (tenth,) = extract_numbers("0.4 xG")
    (one,) = extract_numbers("1 xG")
    assert is_supported(rounded, [104.2])
    assert is_supported(tenth, [0.41])
    assert not is_supported(one, [0.71])  # whole numbers may only round facts of 10 or more


def test_sign_is_ignored() -> None:
    assert unsupported_numbers("momentum went from -0.35 to 0.52", [-0.35, 0.52]) == []


def test_planted_number_is_reported() -> None:
    assert unsupported_numbers("A 0.83 xG chance struck at 104.2 km/h", [0.38, 104.2]) == ["0.83"]


def test_numbers_in_collects_all_readings() -> None:
    assert numbers_in("Full-time: NCF 2-1 HBU, 1,234 passes") == {2.0, 1.0, 1234.0, 1.234}


@pytest.mark.parametrize(
    ("text", "language", "expected"),
    [
        ("scored in the eleventh minute; one in four chances go in", Language.EN, [{11.0}, {4.0}]),
        ("forty-seven percent, his twenty-first goal, two-goal lead", Language.EN, [{47.0}, {21.0}, {2.0}]),
        (
            "quatre fois sur dix, vingt-cinq, quatre-vingt-dix-sept, soixante et onze",
            Language.FR,
            [{4.0}, {10.0}, {25.0}, {97.0}, {71.0}],
        ),
        ("treinta y cinco tiros, veinticinco pases, dos goles", Language.ES, [{35.0}, {25.0}, {2.0}]),
        ("خمسة وعشرون تسديدة و ثلاثة عشر ركنية و أربع مرات", Language.AR, [{25.0}, {13.0}, {4.0}]),
    ],
)
def test_number_words_are_read_in_each_language(text: str, language: Language, expected: list[set[float]]) -> None:
    assert [{r.value for r in t.readings} for t in extract_numbers(text, language)] == expected


@pytest.mark.parametrize(
    ("text", "language"),
    [
        ("a goal in the second half, then a 2nd half rally", Language.EN),
        ("un but en seconde mi-temps", Language.FR),
        ("un gol en el segundo tiempo", Language.ES),
        ("هدف في الشوط الثاني", Language.AR),
        ("one of the best chances, a quick one-two, the first goal", Language.EN),
        ("les deux équipes perdent souvent le ballon", Language.FR),
        ("los dos equipos presionan", Language.ES),
    ],
)
def test_halves_both_and_words_for_one_are_not_counted(text: str, language: Language) -> None:
    assert extract_numbers(text, language) == []


def test_lists_leading_zeros_and_glued_units() -> None:
    assert values("minutes 9,27,33") == [{9.0}, {27.0}, {33.0}]
    assert values("0.123") == [{0.123}]  # never read as 123
    assert values("xG0.38") == [{0.38}]


def test_number_words_must_be_facts_too() -> None:
    assert unsupported_numbers("quatre fois sur dix", [0.38], Language.FR) == ["quatre", "dix"]
    assert unsupported_numbers("in the ninth minute", [9.0]) == []
