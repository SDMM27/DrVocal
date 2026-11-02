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
