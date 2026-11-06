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
    ("arrête Claude", "claude.stop", {}),
    ("Stop Claude.", "claude.stop", {}),
    ("arrête la session Claude", "claude.stop", {}),
    ("arrête la session de Claude", "claude.stop", {}),
    ("Mets Daft Punk !", "spotify.play", {"query": "Daft Punk"}),
    ("mets ferme discord", "spotify.play", {"query": "ferme discord"}),
])
def test_parse(text, action, args, settings):
    assert parse(text, settings) == Intent(action, args)


@pytest.mark.parametrize("text", [
    "", "   ", "euh", "supprime tous mes fichiers", "ferme discord", "ferme le jeu"])
def test_unknown_or_forbidden_gives_none(text, settings):
    assert parse(text, settings) is None


# Transcriptions reelles ou mesurees de "mets daft punk" avec faster-whisper small.
@pytest.mark.parametrize("text,query", [
    ("Medaft Punk", "daft Punk"),
    ("Mais d'aft punk.", "d'aft punk"),
    ("mais du Daft Punk.", "Daft Punk"),
    ("Mets du Daft Punk", "Daft Punk"),
    ("joue des", "des"),
    ("Mais d'arrière ! Mais d'arrière !", "d'arrière"),
    ("joue d'Ariana sur Spotify", "d'Ariana"),
    ("Je joue Daryana sur Spotify.", "Daryana"),
    ("mets Daft Punk dans Spotify", "Daft Punk"),
    ("mets sur spotify", "sur spotify"),
])
def test_misheard_play_is_still_play(text, query, settings):
    assert parse(text, settings) == Intent("spotify.play", {"query": query})


@pytest.mark.parametrize("text", [
    "merci", "message", "mais non je rigole pas du tout", "mais", "medaft"])
def test_misheard_play_rejects_ordinary_speech(text, settings):
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


def test_different_sentences_are_not_merged(settings):
    assert parse("Pause. Musique suivante.", settings) is None


@pytest.mark.parametrize("text,query", [
    ("J'ouvre ma playlist Disco tier 4 sur Spotify.", "Disco tier 4"),
    ("Je vous ma playlist Rital list sur Spotify.", "Rital list"),
    ("lance ma playlist sport", "sport"),
    ("mets la playlist de chill", "chill"),
])
def test_my_playlist_anywhere_in_short_sentence(text, query, settings):
    mine = {"mine": "1"} if " ma " in text.lower() or " ma playlist" in text.lower() else {}
    assert parse(text, settings) == Intent("spotify.play", {"query": query, "kind": "playlist", **mine})


@pytest.mark.parametrize("text", ["lance le DJ sur Spotify", "mets le DJ", "DJ", "lance le di-jay",
                                  "Laisse le DJ.", "Là c'est DJ"])
def test_dj(text, settings):
    assert parse(text, settings) == Intent("spotify.dj", {})


def test_playlist_inside_discord_message_stays_a_message(settings):
    assert parse("écris dans général la playlist est cool", settings).action == "discord.message"


def test_artist_named_dj_is_still_a_search(settings):
    assert parse("mets DJ Snake", settings) == Intent("spotify.play", {"query": "DJ Snake"})


@pytest.mark.parametrize("text", ["mets de la musique", "lance la musique", "joue de la musique sur Spotify"])
def test_generic_music_request_resumes(text, settings):
    assert parse(text, settings) == Intent("spotify.resume", {})


@pytest.mark.parametrize("text,query", [
    ("Lance ma playlist, Rital List sur Spotify", "Rital List"),
    ("Lance, ma playlist Rital List sur Spotify.", "Rital List"),
])
def test_inner_punctuation_from_whisper_is_ignored_for_playlists(text, query, settings):
    assert parse(text, settings) == Intent("spotify.play", {"query": query, "kind": "playlist", "mine": "1"})


def test_inner_punctuation_is_stripped_from_play_queries(settings):
    assert parse("Mets, Daft Punk.", settings) == Intent("spotify.play", {"query": "Daft Punk"})


def test_my_playlist_is_marked_mine_but_the_playlist_is_not(settings):
    assert parse("lance mes playlists sport", settings).args.get("mine") == "1"
    assert "mine" not in parse("lance la playlist sport", settings).args


@pytest.mark.parametrize("text,name", [
    ("Retiens cette playlist sous le nom En boucle", "En boucle"),
    ("retiens cette playlist sous le nom de En boucle.", "En boucle"),
    ("Retiens, cette playlist, comme На повторе.", "На повторе"),
    ("Enregistre cette playlist sous le nom daily mix 1 !", "daily mix 1"),
    ("enregistre cette playlist comme Sport", "Sport"),
    ("Retiens cette playlist en tant que Sport", "Sport"),
    ("Appelle cette playlist Chill", "Chill"),
    ("retiens ce morceau sous le nom Mon tube", "Mon tube"),
    ("retiens ce titre comme Mon tube", "Mon tube"),
    ("enregistre cet album sous le nom Vieux disque", "Vieux disque"),
    ("appelle cet artiste Mon groupe", "Mon groupe"),
])
def test_remember_phrasings(text, name, settings):
    assert parse(text, settings) == Intent("spotify.remember", {"name": name})
