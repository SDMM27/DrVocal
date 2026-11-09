import asyncio
import wave

import numpy as np
import pytest

from drvocal.actions import Catalogue, Outcome
from drvocal.app import (
    Assistant,
    Ears,
    Timings,
    after_wake_phrase,
    register_claude,
    register_notes,
)
from drvocal.audio.mic import FRAME_SAMPLES
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


def build(script, texts=None, catalogue=None, notify=None, capture=None, wake_phrases=()):
    ears, transcribed = make_ears(script, texts)
    detector, player, speaker = Detector(), Player(), Speaker()
    catalogue = catalogue or FakeCatalogue()
    assistant = Assistant(ears, detector, capture or voice_capture(ears), parse, catalogue,
                          player, speaker, notify, wake_phrases=wake_phrases)
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


async def test_wake_word_during_capture_restarts_the_command():
    # "Docteur, mets... Docteur" : la premiere phrase est jetee, seule la seconde est transcrite
    script = [WAKE, SPEECH, SPEECH, SPEECH, WAKE, *[SILENT] * 4, SPEECH, SPEECH, *SILENCE_END, *GAP]
    heard: list[int] = []

    def transcribe(audio: np.ndarray) -> str:
        heard.append(int((audio[::FRAME_SAMPLES] == SPEECH).sum()))
        return "pause"

    ears = Ears(feed(script), transcribe, lambda: is_speech)
    player, catalogue = Player(), FakeCatalogue()
    assistant = Assistant(ears, Detector(), lambda: ears.listen(700, 2000, 15000), parse, catalogue,
                          player, Speaker())
    await run_assistant(assistant)
    assert heard == [2]  # une seule transcription, sans les 3 trames de la phrase abandonnee
    assert catalogue.ran == [Intent("spotify.pause", {})]
    assert player.played == ["wake", "wake", "success"]


PHRASES = ["salut doc vocal"]


@pytest.mark.parametrize(("text", "expected"), [
    ("demande à Claude sur Dr Vocal de lancer les tests", None),
    ("mets du jazz salut docteur vocal mets pause", "mets pause"),
    ("Salut, Dr Vocal. Pause. ", "Pause. "),
    ("Salut doc vocal", ""),
    ("mets salut doc vocal", ""),
    ("mets salut doc vocal.", ""),
    ("", None),
])
def test_after_wake_phrase(text, expected):
    assert after_wake_phrase(text, PHRASES) == expected


def test_after_wake_phrase_keeps_what_follows_the_last_occurrence():
    assert after_wake_phrase("salut doc vocal mets salut docteur vocal pause", PHRASES) == "pause"


async def _midsentence_wake(texts, script):
    heard: list[int] = []
    answers = iter(texts)

    def transcribe(audio: np.ndarray) -> str:
        heard.append(int((audio[::FRAME_SAMPLES] == SPEECH).sum()))
        return next(answers)

    ears = Ears(feed(script), transcribe, lambda: is_speech)
    player, catalogue = Player(), FakeCatalogue()
    assistant = Assistant(ears, Detector(), lambda: ears.listen(700, 2000, 15000), parse, catalogue,
                          player, Speaker(), wake_phrases=PHRASES)
    await run_assistant(assistant)
    return heard, player, catalogue


async def test_wake_word_mid_sentence_keeps_the_whole_sentence_without_wake_phrase():
    script = [WAKE, SPEECH, SPEECH, WAKE, WAKE, SPEECH, *SILENCE_END, *GAP]
    heard, player, catalogue = await _midsentence_wake(["pause"], script)
    assert heard == [3]  # une seule transcription, de toute la phrase
    assert catalogue.ran == [Intent("spotify.pause", {})]
    assert player.played == ["wake", "success"]


async def test_wake_word_mid_sentence_keeps_what_follows_the_wake_phrase():
    script = [WAKE, SPEECH, SPEECH, WAKE, SPEECH, *SILENCE_END, *GAP]
    heard, player, catalogue = await _midsentence_wake(["mets du jazz salut docteur vocal pause"], script)
    assert heard == [3]
    assert catalogue.ran == [Intent("spotify.pause", {})]
    assert player.played == ["wake", "success"]


async def test_transcription_ending_with_wake_phrase_listens_again():
    script = [WAKE, SPEECH, WAKE, SPEECH, *SILENCE_END, *[SILENT] * 6, SPEECH, SPEECH, *SILENCE_END, *GAP]
    heard, player, catalogue = await _midsentence_wake(["mets salut doc vocal", "pause"], script)
    assert heard == [2, 2]
    assert catalogue.ran == [Intent("spotify.pause", {})]
    assert player.played == ["wake", "wake", "success"]


async def test_wake_word_during_transcription_discards_the_result_with_wake_phrases():
    started, release = asyncio.Event(), asyncio.Event()
    captures = []

    async def slow_capture():
        captures.append(1)
        if len(captures) == 1:
            started.set()
            await release.wait()
            return "pause"
        return "pause"

    script = [WAKE, *[SILENT] * 5, WAKE, *GAP]
    assistant, _, _, player, _, catalogue, _ = build(script, capture=slow_capture, wake_phrases=PHRASES)
    await run_assistant(assistant)
    assert len(captures) == 2
    assert player.played == ["wake", "wake", "success"]


async def test_wake_word_during_transcription_discards_the_result():
    started, release = asyncio.Event(), asyncio.Event()
    captures = []

    async def slow_capture():
        captures.append(1)
        if len(captures) == 1:
            started.set()
            await release.wait()  # transcription qui s'eternise
            return "pause"
        return "pause"

    script = [WAKE, *[SILENT] * 5, WAKE, *GAP]
    assistant, _, _, player, _, catalogue, _ = build(script, capture=slow_capture)
    await run_assistant(assistant)
    assert len(captures) == 2
    assert catalogue.ran == [Intent("spotify.pause", {})]  # une seule commande
    assert player.played == ["wake", "wake", "success"]


async def test_wake_word_ignored_while_an_action_listens():
    async def listening_action():
        return await ears.listen(700, 240, 15000)

    script = [WAKE, SPEECH, *SILENCE_END, WAKE, SPEECH, *SILENCE_END, *GAP]
    ears, _ = make_ears(script, texts=["pause", "dictee"])
    heard = []

    class Listening(FakeCatalogue):
        async def run(self, intent):
            heard.append(await listening_action())
            return Outcome(True)

    detector, player = Detector(), Player()
    assistant = Assistant(ears, detector, voice_capture(ears), parse, Listening(), player, Speaker())
    await run_assistant(assistant)
    assert heard == ["dictee"]  # le mot de reveil pendant une dictee ne relance rien
    assert player.played == ["wake", "success"]


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
    await asyncio.wait_for(ears.pump(lambda f, listening: None), 5)
    assert await asyncio.wait_for(listener, 5) == "pause"


async def listen_during_pump(ears: Ears, coro):
    task = asyncio.create_task(coro)
    await asyncio.sleep(0)  # l'ecouteur est ouvert avant la premiere trame
    await asyncio.wait_for(ears.pump(lambda f, listening: None), 10)
    return await asyncio.wait_for(task, 10)


async def test_key_mode_records_only_while_held():
    ears, transcribed = make_ears([SPEECH] * 20)
    held = iter([True] * 6)
    idle = []
    task = asyncio.create_task(ears.record_while(lambda: next(held, False), 15000))
    await asyncio.sleep(0)
    await asyncio.wait_for(ears.pump(lambda f, listening: None if listening else idle.append(f)), 10)
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


class FakeVoice:
    def __init__(self, result: bool = True):
        self.result = result
        self.calls: list[tuple] = []

    async def prompt(self, project, text):
        self.calls.append(("prompt", project, text))
        return self.result

    async def proceed(self, text):
        self.calls.append(("proceed", text))
        return self.result

    async def stop(self):
        self.calls.append(("stop",))
        return self.result

    async def import_all(self):
        self.calls.append(("import",))
        return self.result


async def test_register_claude_without_voice_registers_nothing():
    catalogue = Catalogue()
    register_claude(catalogue, None)
    for action in ("claude.prompt", "claude.continue", "claude.stop", "claude.import"):
        out = await catalogue.run(Intent(action, {"project": "x", "prompt": "x"}))
        assert out.ok is False


@pytest.mark.parametrize("intent, call", [
    (Intent("claude.prompt", {"project": "geogame", "prompt": "fais x"}), ("prompt", "geogame", "fais x")),
    (Intent("claude.continue", {"prompt": "encore"}), ("proceed", "encore")),
    (Intent("claude.stop", {}), ("stop",)),
    (Intent("claude.import", {}), ("import",)),
])
@pytest.mark.parametrize("result", [True, False])
async def test_claude_actions_call_the_voice_and_report_its_result(intent, call, result):
    catalogue, voice = Catalogue(), FakeVoice(result)
    register_claude(catalogue, voice)  # type: ignore[arg-type]
    out = await catalogue.run(intent)
    assert out.ok is result
    assert voice.calls == [call]


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


async def test_listen_keeps_debug_capture_including_silent_ones(tmp_path):
    ears = Ears(feed([SPEECH, SPEECH, *SILENCE_END, *[SILENT] * 8]), lambda a: "pause", lambda: is_speech, tmp_path)
    pump = asyncio.create_task(ears.pump(lambda f, listening: None))
    assert await ears.listen(700, 240, 15000) == "pause"
    assert await ears.listen(700, 240, 15000) is None  # aucune parole : garde aussi
    pump.cancel()
    files = sorted(tmp_path.glob("*.wav"))
    assert len(files) == 2
    with wave.open(str(files[0])) as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (16000, 1, 2)


async def test_listen_without_captures_dir_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ears = Ears(feed([SPEECH, *SILENCE_END]), lambda a: "pause", lambda: is_speech)
    pump = asyncio.create_task(ears.pump(lambda f, listening: None))
    await ears.listen(700, 240, 15000)
    pump.cancel()
    assert list(tmp_path.rglob("*.wav")) == []


def test_debug_captures_are_capped(tmp_path):
    ears = Ears(feed([]), lambda a: "", lambda: is_speech, tmp_path)
    for i in range(25):
        (tmp_path / f"2000-01-01_00-00-{i:02d}-000000.wav").write_bytes(b"")
    ears._keep_capture([frame(SPEECH)])
    assert len(list(tmp_path.glob("*.wav"))) == 20


class Journal:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[tuple] = []
        self.error = error

    def __call__(self, text, intent, ok, audio, stt_ms, action_ms) -> None:
        self.calls.append((text, intent, ok, audio, stt_ms, action_ms))
        if self.error is not None:
            raise self.error


def build_logged(script, journal, texts=None, catalogue=None):
    ears, transcribed = make_ears(script, texts)
    catalogue = catalogue or FakeCatalogue()
    assistant = Assistant(ears, Detector(), voice_capture(ears), parse, catalogue, Player(), Speaker(),
                          command_log=journal)
    return assistant, catalogue, transcribed


async def test_unparsed_command_is_logged_without_intent():
    journal = Journal()
    assistant, _, _ = build_logged([WAKE, SPEECH, *SILENCE_END, *GAP], journal, texts=["blabla"])
    await run_assistant(assistant)
    [(text, intent, ok, audio, stt_ms, action_ms)] = journal.calls
    assert text == "blabla" and intent is None and ok is None and action_ms is None
    assert audio is not None and len(audio) > 0 and stt_ms is not None


async def test_executed_command_is_logged_with_action_and_outcome():
    journal = Journal()
    assistant, _, _ = build_logged([WAKE, SPEECH, *SILENCE_END, *GAP], journal)
    await run_assistant(assistant)
    [(text, intent, ok, _, _, action_ms)] = journal.calls
    assert text == "pause" and intent == Intent("spotify.pause", {}) and ok is True
    assert action_ms is not None and action_ms >= 0


async def test_failed_and_raising_actions_are_logged_not_ok():
    for outcome in (Outcome(False), RuntimeError("boum")):
        journal = Journal()
        assistant, _, _ = build_logged([WAKE, SPEECH, *SILENCE_END, *GAP], journal,
                                       catalogue=FakeCatalogue(outcome))
        await run_assistant(assistant)
        assert journal.calls[0][2] is False


async def test_logged_audio_is_the_command_even_if_action_listens_again():
    journal = Journal()
    script = [WAKE, SPEECH, SPEECH, *SILENCE_END, *[SILENT] * 30, *[SPEECH] * 6, *SILENCE_END, *GAP]
    ears = Ears(feed(script, 0.02), lambda audio: transcribed.append(len(audio)) or next(answers), lambda: is_speech)
    transcribed: list[int] = []
    answers = iter(["pause", "autre"])

    class Listening(FakeCatalogue):
        async def run(self, intent):
            self.ran.append(intent)
            await ears.listen(700, 3000, 15000)
            return Outcome(True)

    assistant = Assistant(ears, Detector(), voice_capture(ears), parse, Listening(), Player(), Speaker(),
                          command_log=journal)
    await run_assistant(assistant)
    assert len(transcribed) == 2 and transcribed[0] != transcribed[1]
    assert len(journal.calls[0][3]) == transcribed[0]


async def test_failing_journal_does_not_break_the_command():
    journal = Journal(RuntimeError("disque plein"))
    assistant, catalogue, _ = build_logged([WAKE, SPEECH, *SILENCE_END, *GAP], journal)
    await run_assistant(assistant)
    assert catalogue.ran == [Intent("spotify.pause", {})]
    assert len(journal.calls) == 1


class Events:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[tuple] = []
        self.error = error

    def __call__(self, kind, **fields) -> None:
        self.calls.append((kind, fields))
        if self.error is not None:
            raise self.error


async def test_false_wake_is_journaled_as_no_speech():
    events = Events()
    ears, _ = make_ears([WAKE, *[SILENT] * 8, *GAP])
    assistant = Assistant(ears, Detector(), voice_capture(ears), parse, FakeCatalogue(), Player(), Speaker(),
                          event_log=events)
    await run_assistant(assistant)
    assert events.calls == [("no_speech", {})]


async def test_failing_event_log_does_not_break_the_wake():
    events = Events(RuntimeError("disque plein"))
    ears, _ = make_ears([WAKE, *[SILENT] * 8, *GAP])
    player = Player()
    assistant = Assistant(ears, Detector(), voice_capture(ears), parse, FakeCatalogue(), player, Speaker(),
                          event_log=events)
    await run_assistant(assistant)
    assert len(events.calls) == 1 and player.played == ["wake"]


async def test_reply_is_journaled():
    calls = []

    def journal(text, intent, ok, audio, stt_ms, action_ms, reply=None):
        calls.append((ok, reply))

    ears, _ = make_ears([WAKE, SPEECH, *SILENCE_END, *GAP], ["pause"])
    assistant = Assistant(ears, Detector(), voice_capture(ears), parse,
                          FakeCatalogue(Outcome(False, "Je n'ai pas trouvé")), Player(), Speaker(),
                          command_log=journal)
    await run_assistant(assistant)
    assert calls == [(False, "Je n'ai pas trouvé")]
