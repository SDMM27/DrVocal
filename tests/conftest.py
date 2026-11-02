from pathlib import Path

import pytest

from drvocal.config import Settings


@pytest.fixture
def settings() -> Settings:
    return Settings(
        wake_phrases=["salut docteur"],
        notes_dir=Path("notes"),
        projects={"dr vocal": Path("D:/NasaCode/DrVocal"), "mon site": Path("D:/site")},
        discord_hotkeys={},
        discord_channels={"général": 1, "salon de jeu": 2, "ranked": 3},
        discord_members={"paul": 10},
        spotify_client_id="",
        discord_bot_token="",
        stt_model="small",
        stt_device="cpu",
        second_screen_index=0,
    )
