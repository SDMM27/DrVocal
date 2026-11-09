from pathlib import Path

import pytest

from drvocal.config import load_settings
from drvocal.vocabulary import build_vocabulary, clean_term, make_hotwords


def test_priority_order_and_join():
    assert build_vocabulary([["b", "a"], ["c"]]) == "b, a, c"


def test_dedup_ignores_case_accents_and_empty():
    assert build_vocabulary([["Beyoncé", " ", ""], ["beyonce", "BEYONCÉ", "Zaz"]]) == "Beyoncé, Zaz"


def test_limit_never_cuts_a_term():
    assert build_vocabulary([["aaaa", "bbbb", "cccc"]], max_chars=10) == "aaaa, bbbb"
    assert build_vocabulary([["aaaa", "bbbbbbbbbbbbbb"]], max_chars=10) == "aaaa"


def test_make_hotwords_order_with_and_without_spotify(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text('stt_vocabulary = ["Daft Punk"]\n[projects]\n"Dr Vocal" = "D:/x"\n'
                    '[discord.channels]\ngeneral = 1\n[discord.members]\nalex = 2\n', encoding="utf-8")
    s = load_settings(path)
    assert make_hotwords(s)() == "Daft Punk, dr vocal, general, alex"
    assert make_hotwords(s, lambda: ["Zaz", "alex"])() == "Daft Punk, dr vocal, general, alex, Zaz"


@pytest.mark.parametrize("raw, expected", [
    ("Metal 🤘🎸", "Metal"),
    ("Bonne humeur ☀️🌞", "Bonne humeur"),
    ("Δ 𝐂𝐋𝐔𝐁 𝐇𝐄𝐋𝐋", "CLUB HELL"),
    ("Яндекс Чарт | Yandex Chart | 2026 ✔", "Yandex Chart 2026"),
    ("Rock & Ролл", "Rock"),
    ("1940’s Detective Jazz", "1940's Detective Jazz"),
    ("+ 999999 AURA ☠️", "999999 AURA"),
    ("lilya 4-ever", "lilya 4-ever"),
    ("Beyoncé", "Beyoncé"),
    ("Русский Поп 🇷🇺", ""),
    ("2026", ""),
])
def test_clean_term_keeps_only_latin_words(raw, expected):
    assert clean_term(raw) == expected


def test_vocabulary_drops_unusable_terms():
    assert build_vocabulary([["Сестры Ost", "🎶", "Metal 🤘"]]) == "Ost, Metal"
