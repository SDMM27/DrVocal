import asyncio
from pathlib import Path

import numpy as np
import pytest

from drvocal.actions import Catalogue, Outcome
from drvocal.app import (
    Assistant,
    Ears,
    Timings,
    make_ask_user,
    make_event_handler,
    register_claude,
    register_notes,
)
from drvocal.audio.mic import FRAME_SAMPLES
from drvocal.claude_policy import Reply
from drvocal.claude_session import SessionEvent
from drvocal.intent import Intent

SILENT, SPEECH, WAKE = 0, 1, 2  # marqueur place dans le premier echantillon de chaque trame
DELAY = 0.004
SILENCE_END = [SILENT] * 10  # > 700 ms de silence : fin de phrase
GAP = [SILENT] * 12  # laisse le temps de retomber en veille


def frame(kind: int) -> np.ndarray:
    f = np.zeros(FRAME_SAMPLES, dtype=np.int16)
    f[0] = kind
    return f


async def feed(script: list[int], delay: float = DELAY):
    for kind in script:
        yield frame(kind)
        await asyncio.sleep(delay)


def is_speech(f: np.ndarray) -> bool:
    return f[0] == SPEECH


class Detector:
    def __init__(self) -> None:
        self.calls = 0

    def process(self, f: np.ndarray) -> bool:
        self.calls += 1
        return bool(f[0] == WAKE)


class Player:
    def __init__(self) -> None:
        self.played: list[str] = []

    def play(self, name: str) -> None:
        self.played.append(name)


class Speaker:
    def __init__(self) -> None:
        self.said: list[str] = []

    async def say(self, text: str) -> None:
        self.said.append(text)


class FakeCatalogue:
    def __init__(self, outcome: Outcome | Exception = Outcome(True), gate: asyncio.Event | None = None):
        self.outcome = outcome
        self.gate = gate
        self.ran: list[Intent] = []

    async def run(self, intent: Intent) -> Outcome:
        self.ran.append(intent)
        if self.gate is not None:
            await self.gate.wait()
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def parse(text: str) -> Intent | None:
    return Intent("spotify.pause", {}) if text == "pause" else None


def make_ears(script: list[int], texts: list[str] | None = None):
    transcribed: list[int] = []
    answers = iter(texts if texts is not None else [])

    def transcribe(audio: np.ndarray) -> str:
        transcribed.append(len(audio))
        return next(answers, "pause")

    ears = Ears(feed(script), transcribe, lambda: is_speech)
    return ears, transcribed


def voice_capture(ears: Ears):
    return lambda: ears.listen(700, 240, 15000)


async def run_assistant(assistant: Assistant) -> None:
    await asyncio.wait_for(assistant.run(), 10)
    while assistant._tasks:
        await asyncio.wait_for(asyncio.gather(*list(assistant._tasks)), 10)


def build(script, texts=None, catalogue=None, notify=None, capture=None):
    ears, transcribed = make_ears(script, texts)
    detector, player, speaker = Detector(), Player(), Speaker()
    catalogue = catalogue or FakeCatalogue()
    assistant = Assistant(ears, detector, capture or voice_capture(ears), parse, catalogue,
                          player, speaker, notify)
    return assistant, ears, detector, player, speaker, catalogue, transcribed


async def test_nothing_transcribed_before_wake():
    assistant, _, detector, player, _, catalogue, transcribed = build([SPEECH] * 5 + SILENCE_END + [SPEECH] * 3)
    await run_assistant(assistant)
    assert transcribed == [] and player.played == [] and catalogue.ran == []
    assert detector.calls == 18


async def test_wake_plays_sound_then_runs_action():
    assistant, _, _, player, _, catalogue, transcribed = build([WAKE, SPEECH, SPEECH, *SILENCE_END, *GAP])
    await run_assistant(assistant)
    assert len(transcribed) == 1
    assert catalogue.ran == [Intent("spotify.pause", {})]
    assert player.played == ["wake", "success"]


async def test_false_wake_returns_to_idle_without_action():
    assistant, _, _, player, _, catalogue, transcribed = build([WAKE, *[SILENT] * 8, *GAP])
    await run_assistant(assistant)
    assert player.played == ["wake"]
    assert catalogue.ran == [] and transcribed == []


async def test_unparsed_plays_failure_sound():
    assistant, _, _, player, _, catalogue, _ = build(
        [WAKE, SPEECH, *SILENCE_END, *GAP], texts=["blabla"])
    await run_assistant(assistant)
    assert player.played == ["wake", "failure"]
    assert catalogue.ran == []


async def test_failed_outcome_plays_failure_sound():
    assistant, *_, player, _, catalogue, _ = build(
        [WAKE, SPEECH, *SILENCE_END, *GAP], catalogue=FakeCatalogue(Outcome(False)))
    await run_assistant(assistant)
    assert player.played == ["wake", "failure"]


async def test_handler_exception_does_not_stop_loop():
    class Flaky(FakeCatalogue):
        async def run(self, intent):
            self.ran.append(intent)
            if len(self.ran) == 1:
                raise RuntimeError("boum")
            return Outcome(True)

    script = [WAKE, SPEECH, *SILENCE_END, *GAP, WAKE, SPEECH, *SILENCE_END, *GAP]
    assistant, _, _, player, _, catalogue, _ = build(script, catalogue=Flaky())
    await run_assistant(assistant)
    assert len(catalogue.ran) == 2
    assert player.played == ["wake", "failure", "wake", "success"]


async def test_transcription_exception_does_not_stop_loop():
    calls = []

    def transcribe(audio):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("whisper")
        return "pause"

    script = [WAKE, SPEECH, *SILENCE_END, *GAP, WAKE, SPEECH, *SILENCE_END, *GAP]
    ears = Ears(feed(script), transcribe, lambda: is_speech)
    player = Player()
    catalogue = FakeCatalogue()
    assistant = Assistant(ears, Detector(), voice_capture(ears), parse, catalogue, player, Speaker())
    await run_assistant(assistant)
    assert player.played == ["wake", "wake", "success"]


async def test_success_is_silent_except_sound():
    notified: list[str] = []
    assistant, _, _, player, speaker, _, _ = build(
        [WAKE, SPEECH, *SILENCE_END, *GAP],
        catalogue=FakeCatalogue(Outcome(True, "Lecture lancée")), notify=notified.append)
    await run_assistant(assistant)
    assert speaker.said == []
    assert notified == ["Lecture lancée"]
    assert player.played == ["wake", "success"]


async def test_wake_ignored_while_handling():
    captures = []

    async def slow_capture():
        captures.append(1)
        await asyncio.sleep(0.15)
        return None

    script = [WAKE, SILENT, WAKE, SILENT, WAKE, SILENT, *[SILENT] * 60]
    assistant, _, detector, player, *_ = build(script, capture=slow_capture)
    await run_assistant(assistant)
    assert len(captures) == 1
    assert player.played == ["wake"]


async def test_long_action_does_not_block_next_wake():
    gate = asyncio.Event()
    catalogue = FakeCatalogue(gate=gate)

    async def instant_capture():
        return "pause"

    script = [WAKE, *GAP, WAKE, *GAP]
    assistant, _, _, player, *_ = build(script, catalogue=catalogue, capture=instant_capture)
    await asyncio.wait_for(assistant.run(), 10)
    assert len(catalogue.ran) == 2  # la deuxieme commande part pendant que la premiere tourne
    assert player.played == ["wake", "wake"]
    gate.set()
    await asyncio.wait_for(asyncio.gather(*list(assistant._tasks)), 10)
    assert player.played == ["wake", "wake", "success", "success"]


async def test_pump_end_releases_listener():
    ears, _ = make_ears([SPEECH, SPEECH])
    listener = asyncio.create_task(ears.listen(700, 5000, 15000))
    await asyncio.sleep(0)
    await asyncio.wait_for(ears.pump(lambda f: None), 5)
    assert await asyncio.wait_for(listener, 5) == "pause"


async def listen_during_pump(ears: Ears, coro):
    task = asyncio.create_task(coro)
    await asyncio.sleep(0)  # l'ecouteur est ouvert avant la premiere trame
    await asyncio.wait_for(ears.pump(lambda f: None), 10)
    return await asyncio.wait_for(task, 10)


async def test_key_mode_records_only_while_held():
    ears, transcribed = make_ears([SPEECH] * 20)
    held = iter([True] * 6)
    idle = []
    task = asyncio.create_task(ears.record_while(lambda: next(held, False), 15000))
    await asyncio.sleep(0)
    await asyncio.wait_for(ears.pump(idle.append), 10)
    assert await task == "pause"
    assert transcribed == [8 * FRAME_SAMPLES]  # 6 trames tenues + 2 de traine
    assert len(idle) == 12  # le reste du flux retourne au detecteur


async def test_short_key_press_is_ignored():
    ears, transcribed = make_ears([SPEECH] * 10)
    held = iter([True, True])  # 160 ms < 300 ms
    result = await listen_during_pump(ears, ears.record_while(lambda: next(held, False), 15000))
    assert result is None and transcribed == []


async def test_key_recording_stops_at_max():
    ears, transcribed = make_ears([SPEECH] * 30)
    result = await listen_during_pump(ears, ears.record_while(lambda: True, max_ms=800))
    assert result == "pause" and transcribed == [10 * FRAME_SAMPLES]


async def test_key_mode_through_assistant():
    held = iter([True] * 5)
    script = [WAKE, *[SPEECH] * 20]
    ears, transcribed = make_ears(script)
    player, catalogue = Player(), FakeCatalogue()
    capture = lambda: ears.record_while(lambda: next(held, False), 15000)  # noqa: E731
    assistant = Assistant(ears, Detector(), capture, parse, catalogue, player, Speaker())
    await run_assistant(assistant)
    assert player.played == ["wake", "success"] and len(transcribed) == 1


async def test_cancel_detects_annule():
    for said, expected in [("Annule !", True), ("annuler", True), ("Annulé", True), ("continue", False)]:
        ears, _ = make_ears([SPEECH, SPEECH, *SILENCE_END], texts=[said])
        assert await listen_during_pump(ears, ears.wait_for_cancel(1)) is expected, said


async def test_cancel_false_without_speech():
    ears, transcribed = make_ears([SILENT] * 20)
    assert await listen_during_pump(ears, ears.wait_for_cancel(0.24)) is False
    assert transcribed == []


class FakeListener:
    def __init__(self, answer: str | None):
        self.answer = answer
        self.calls: list[tuple] = []

    async def listen(self, *args):
        self.calls.append(args)
        return self.answer


async def test_claude_question_listens_without_wake():
    timings = Timings()
    ears, speaker = FakeListener("Le projet Alpha"), Speaker()
    ask = make_ask_user(ears, speaker, timings)
    assert await ask("Quel projet ?", "question") == "Le projet Alpha"
    assert speaker.said == ["Quel projet ?"]
    assert ears.calls == [(900, 8000, 15000)]
    assert await make_ask_user(FakeListener(None), Speaker(), timings)("Et ?", "question") == ""


@pytest.mark.parametrize("said, expected", [
    ("oui docteur", Reply.APPROVE),
    ("Oui, docteur !", Reply.APPROVE),
    ("non docteur", Reply.REJECT),
    ("oui", Reply.NONE),
    ("oui vas-y", Reply.NONE),
    (None, Reply.NONE),
])
async def test_approval_requires_exact_phrase(said, expected):
    ask = make_ask_user(FakeListener(said), Speaker(), Timings())
    assert await ask("Autoriser ?", "approval") is expected


class FakeRunner:
    def __init__(self):
        self.started: list[tuple] = []
        self.resumed: list[str] = []

    async def start(self, project, prompt):
        self.started.append((project, prompt))

    async def resume(self, prompt):
        self.resumed.append(prompt)


async def test_unknown_project_starts_nothing(settings):
    catalogue, runner = Catalogue(), FakeRunner()
    register_claude(catalogue, runner, settings)
    out = await catalogue.run(Intent("claude.prompt", {"project": "inconnu", "prompt": "fais x"}))
    await asyncio.sleep(0.01)
    assert out.ok is False and runner.started == []


async def test_claude_prompt_and_continue_run_in_background(settings):
    catalogue, runner = Catalogue(), FakeRunner()
    register_claude(catalogue, runner, settings)
    out = await catalogue.run(Intent("claude.prompt", {"project": "mon site", "prompt": "fais x"}))
    assert out.ok is True
    out = await catalogue.run(Intent("claude.continue", {"prompt": "encore"}))
    assert out.ok is True
    await asyncio.sleep(0.01)
    assert runner.started == [(Path("D:/site"), "fais x")]
    assert runner.resumed == ["encore"]


async def test_note_uses_long_silence(tmp_path):
    from datetime import datetime

    ears, player = FakeListener("ma note"), Player()
    catalogue = Catalogue()
    register_notes(catalogue, ears, tmp_path, player, Timings(), now=lambda: datetime(2026, 11, 3, 10, 0, 0))
    out = await catalogue.run(Intent("notes.start", {}))
    assert out.ok is True
    assert ears.calls == [(2500, 6000, 120000)]
    assert player.played == ["wake"]
    assert (tmp_path / "2026-11-03_10-00-00.txt").read_text(encoding="utf-8") == "ma note"


async def test_empty_note_is_a_failure(tmp_path):
    catalogue = Catalogue()
    register_notes(catalogue, FakeListener(None), tmp_path, Player(), Timings())
    assert (await catalogue.run(Intent("notes.start", {}))).ok is False
    assert list(tmp_path.iterdir()) == []


def test_event_handler_sounds_and_push():
    player, pushed = Player(), []
    on_event = make_event_handler(player, pushed.append)
    for kind in ("text", "tool", "pending", "done", "error"):
        on_event(SessionEvent(kind, "x"))
    assert player.played == ["done", "failure"]
    assert len(pushed) == 5
