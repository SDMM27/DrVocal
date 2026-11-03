"""Assemblage : ecoute du micro, reveil, capture, actions et sons."""
from __future__ import annotations

import asyncio
import logging
import unicodedata
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from drvocal.actions import Catalogue, Outcome
from drvocal.actions_notes import save_note
from drvocal.audio.mic import FRAME_MS
from drvocal.audio.vad import capture_utterance
from drvocal.audio.wake import WakeEngine
from drvocal.claude_policy import Reply, parse_reply
from drvocal.claude_session import ClaudeRunner, SessionEvent
from drvocal.config import Settings
from drvocal.intent import Intent

log = logging.getLogger(__name__)

_TRAILING_FRAMES = 2  # trames gardees apres le relachement de la touche


@dataclass(frozen=True)
class Timings:
    command_silence_ms: int = 700
    command_no_speech_ms: int = 3000
    command_max_ms: int = 15000
    note_silence_ms: int = 2500
    note_no_speech_ms: int = 6000
    note_max_ms: int = 120000
    reply_silence_ms: int = 900
    reply_no_speech_ms: int = 8000
    reply_max_ms: int = 15000
    key_max_ms: int = 15000


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


class Ears:
    """Seul proprietaire du flux micro : les trames vont a l'ecouteur actif, sinon au detecteur de reveil.

    Rien n'est capture ni transcrit hors d'un ecouteur actif.
    """

    def __init__(
        self,
        frames: AsyncIterator[np.ndarray],
        transcribe: Callable[[np.ndarray], str],
        is_speech_factory: Callable[[], Callable[[np.ndarray], bool]],
    ) -> None:
        self._frames = frames
        self._transcribe = transcribe
        self._is_speech_factory = is_speech_factory
        self._queue: asyncio.Queue[np.ndarray | None] | None = None
        self._lock = asyncio.Lock()
        self._closed = False

    async def pump(self, on_idle_frame: Callable[[np.ndarray], None]) -> None:
        try:
            async for frame in self._frames:
                queue = self._queue
                if queue is not None:
                    queue.put_nowait(frame)
                else:
                    on_idle_frame(frame)
        finally:
            self._closed = True
            if self._queue is not None:
                self._queue.put_nowait(None)  # flux termine : libere l'ecouteur

    def _open(self) -> asyncio.Queue[np.ndarray | None]:
        self._queue = asyncio.Queue()
        if self._closed:
            self._queue.put_nowait(None)
        return self._queue

    @staticmethod
    async def _drain(queue: asyncio.Queue[np.ndarray | None]) -> AsyncIterator[np.ndarray]:
        while True:
            frame = await queue.get()
            if frame is None:
                return
            yield frame

    async def _text(self, audio: np.ndarray) -> str | None:
        text = await asyncio.to_thread(self._transcribe, audio)
        log.debug("transcription : %s", text)
        return text.strip() or None

    async def listen(self, silence_ms: int, no_speech_timeout_ms: int, max_ms: int) -> str | None:
        async with self._lock:
            queue = self._open()
            try:
                audio = await capture_utterance(
                    self._drain(queue), silence_ms, no_speech_timeout_ms, max_ms,
                    is_speech=self._is_speech_factory())
            finally:
                self._queue = None
            if audio is None:
                return None
            return await self._text(audio)

    async def record_while(self, held: Callable[[], bool], max_ms: int, min_ms: int = 300) -> str | None:
        """Enregistre tant que `held()` est vrai (verifie a chaque trame), plus 2 trames de traine."""
        async with self._lock:
            queue = self._open()
            frames: list[np.ndarray] = []
            held_ms = 0
            tail = 0
            try:
                async for frame in self._drain(queue):
                    frames.append(frame)
                    if held():
                        held_ms += FRAME_MS
                        tail = 0
                    else:
                        tail += 1
                        if tail >= _TRAILING_FRAMES:
                            break
                    if len(frames) * FRAME_MS >= max_ms:
                        break
            finally:
                self._queue = None
            if held_ms < min_ms:
                return None
            return await self._text(np.concatenate(frames))

    async def wait_for_cancel(self, seconds: float) -> bool:
        text = await self.listen(silence_ms=700, no_speech_timeout_ms=int(seconds * 1000), max_ms=5000)
        return text is not None and "annule" in _fold(text)


class Assistant:
    """Boucle principale : reveil, son, capture, parse, action en tache de fond, son de resultat."""

    def __init__(
        self,
        ears: Ears,
        detector: WakeEngine,
        capture_command: Callable[[], Awaitable[str | None]],
        parse: Callable[[str], Intent | None],
        catalogue: Catalogue,
        player: Any,
        speaker: Any,
        notify: Callable[[str], None] | None = None,
    ) -> None:
        self._ears = ears
        self._detector = detector
        self._capture = capture_command
        self._parse = parse
        self._catalogue = catalogue
        self._player = player
        self._speaker = speaker  # jamais utilise pour repondre : pas de voix par defaut
        self._notify = notify
        self._waking = False
        self._tasks: set[asyncio.Task] = set()

    async def run(self) -> None:
        await self._ears.pump(self._on_frame)

    def _spawn(self, coro: Coroutine[Any, Any, None]) -> None:
        task = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(task)  # reference forte jusqu'a la fin
        task.add_done_callback(self._tasks.discard)

    def _on_frame(self, frame: np.ndarray) -> None:
        if self._waking:
            return
        try:
            woke = self._detector.process(frame)
        except Exception:
            log.exception("detecteur de reveil en erreur")
            return
        if woke:
            self._waking = True
            self._spawn(self._on_wake())

    async def _on_wake(self) -> None:
        try:
            self._player.play("wake")
            text = await self._capture()
            if text is None:
                return  # faux reveil : retour en veille, sans son
            intent = self._parse(text)
            if intent is None:
                log.info("commande non comprise")
                self._player.play("failure")
                return
            self._spawn(self._run_action(intent))
        except Exception:
            log.exception("echec pendant le traitement d'un reveil")
        finally:
            self._waking = False

    async def _run_action(self, intent: Intent) -> None:
        try:
            outcome = await self._catalogue.run(intent)
        except Exception:
            log.exception("action %s en erreur", intent.action)
            outcome = Outcome(False)
        self._player.play("success" if outcome.ok else "failure")
        if outcome.speak:
            log.info("%s : %s", intent.action, outcome.speak)
            if self._notify is not None:
                try:
                    self._notify(outcome.speak)
                except Exception:
                    log.exception("notification impossible")


def register_notes(
    catalogue: Catalogue,
    ears: Ears,
    notes_dir: Path,
    player: Any,
    timings: Timings,
    now: Callable[[], datetime] = datetime.now,
) -> None:
    async def start(_: Intent) -> Outcome:
        player.play("wake")  # debut de dictee
        text = await ears.listen(timings.note_silence_ms, timings.note_no_speech_ms, timings.note_max_ms)
        if text is None:
            return Outcome(False)
        await asyncio.to_thread(save_note, text, notes_dir, now())
        return Outcome(True)

    catalogue.register("notes.start", start)


def register_claude(catalogue: Catalogue, runner: ClaudeRunner, settings: Settings) -> None:
    tasks: set[asyncio.Task] = set()

    def background(coro: Coroutine[Any, Any, None]) -> None:
        async def guarded() -> None:
            try:
                await coro
            except Exception:
                log.exception("session Claude en erreur")

        task = asyncio.get_running_loop().create_task(guarded())
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    async def prompt(intent: Intent) -> Outcome:
        path = settings.projects.get(intent.args.get("project", "").strip().lower())
        if path is None:
            return Outcome(False)
        background(runner.start(path, intent.args["prompt"]))
        return Outcome(True)

    async def proceed(intent: Intent) -> Outcome:
        background(runner.resume(intent.args["prompt"]))
        return Outcome(True)

    catalogue.register("claude.prompt", prompt)
    catalogue.register("claude.continue", proceed)


def make_ask_user(ears: Ears, speaker: Any, timings: Timings) -> Callable[[str, str], Awaitable[Reply | str]]:
    async def ask_user(text: str, kind: str) -> Reply | str:
        await speaker.say(text)
        reply = await ears.listen(timings.reply_silence_ms, timings.reply_no_speech_ms, timings.reply_max_ms)
        if kind == "approval":
            return parse_reply(reply or "")
        return reply or ""

    return ask_user


def make_event_handler(
    player: Any, push: Callable[[SessionEvent], None] | None = None
) -> Callable[[SessionEvent], None]:
    def on_event(event: SessionEvent) -> None:
        if event.kind == "done":
            player.play("done")
        elif event.kind == "error":
            player.play("failure")
        if push is not None:
            try:
                push(event)
            except Exception:
                log.exception("affichage de l'evenement impossible")

    return on_event
