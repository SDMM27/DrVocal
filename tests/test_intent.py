from dataclasses import replace
from pathlib import Path

import pytest

from drvocal.intent import Intent, parse


@pytest.mark.parametrize("text,action,args", [
    ("mets daft punk", "spotify.play", {"query": "daft punk"}),
    ("pause", "spotify.pause", {}),
    ("reprends la musique", "spotify.resume", {}),
    ("musique suivante", "spotify.next", {}),
    ("musique précédente", "spotify.previous", {}),
    ("musique precedente", "spotify.previous", {}),
    ("volume 40", "spotify.volume", {"level": "40"}),
    ("coupe mon micro", "discord.mute_self", {}),
    ("mets-moi en sourdine", "discord.deafen_self", {}),
    ("mets moi en sourdine", "discord.deafen_self", {}),
    ("prends une note", "notes.start", {}),
    ("écris dans général j'arrive", "discord.message", {"channel": "général", "text": "j'arrive"}),
    ("écris dans général j’arrive.", "discord.message", {"channel": "général", "text": "j’arrive"}),
    ("ecris dans salon de jeu salut tout le monde", "discord.message",
     {"channel": "salon de jeu", "text": "salut tout le monde"}),
    ("va dans le salon ranked", "discord.move_self", {"channel": "ranked"}),
    ("mute paul", "discord.mute_member", {"member": "paul"}),
    ("demande à claude sur dr vocal de corriger le test", "claude.prompt",
     {"project": "dr vocal", "prompt": "corriger le test"}),
    ("continue avec claude de ajouter un test", "claude.continue", {"prompt": "ajouter un test"}),
    ("Mets Daft Punk !", "spotify.play", {"query": "Daft Punk"}),
    ("mets ferme discord", "spotify.play", {"query": "ferme discord"}),
])
def test_parse(text, action, args, settings):
    assert parse(text, settings) == Intent(action, args)


@pytest.mark.parametrize("text", [
    "", "   ", "euh", "supprime tous mes fichiers", "ferme discord", "ferme le jeu"])
def test_unknown_or_forbidden_gives_none(text, settings):
    assert parse(text, settings) is None


def test_unknown_project_gives_none(settings):
    assert parse("demande à claude sur inconnu de corriger le test", settings) is None


@pytest.mark.parametrize("text,prompt", [
    ("continue avec claude dessine un logo", "dessine un logo"),
    ("continue avec claude quelque chose", "quelque chose"),
    ("continue avec claude de dessiner", "dessiner"),
    ("continue avec claude d'ajouter un test", "ajouter un test"),
])
def test_continue_prompt_not_truncated(text, prompt, settings):
    assert parse(text, settings) == Intent("claude.continue", {"prompt": prompt})


def test_project_prompt_starting_with_de_not_truncated(settings):
    assert parse("demande à claude sur dr vocal détecte les bugs", settings) == Intent(
        "claude.prompt", {"project": "dr vocal", "prompt": "détecte les bugs"})


def test_synonym_replaces_whole_utterance(settings):
    s = replace(settings, synonyms={"balance la suivante": "musique suivante"})
    assert parse("Balance la suivante !", s) == Intent("spotify.next", {})
    assert parse("balance la suivante", settings) is None


def test_synonym_to_unknown_phrase_gives_none(settings):
    s = replace(settings, synonyms={"fais un truc": "bidule inconnu"})
    assert parse("fais un truc", s) is None


def test_project_name_with_regex_chars(settings):
    s = replace(settings, projects={"c++": Path("x")}, discord_channels={"c++": 1})
    assert parse("demande à claude sur c++ de compiler", s) == Intent(
        "claude.prompt", {"project": "c++", "prompt": "compiler"})
    assert parse("écris dans c++ salut", s) == Intent(
        "discord.message", {"channel": "c++", "text": "salut"})


def test_pause_with_trailing_words_gives_none(settings):
    assert parse("pause demain", settings) is None
