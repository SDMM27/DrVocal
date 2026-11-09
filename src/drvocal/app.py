"""Assemblage : ecoute du micro, reveil, capture, actions et sons."""
from __future__ import annotations

import asyncio
import logging
import re
import time
import unicodedata
import wave
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from drvocal.actions import Catalogue, Outcome
from drvocal.actions_notes import save_note
from drvocal.audio.mic import FRAME_MS, SAMPLE_RATE
from drvocal.audio.vad import capture_utterance
from drvocal.audio.wake import WakeEngine
from drvocal.claude_voice import ClaudeVoice
from drvocal.intent import Intent

log = logging.getLogger(__name__)

_TRAILING_FRAMES = 2  # trames gardees apres le relachement de la touche
_KEPT_CAPTURES = 20  # diagnostic : nombre de WAV gardes dans captures_dir


@dataclass(frozen=True)
class Timings:
    command_silence_ms: int = 700
    command_no_speech_ms: int = 3000
    command_max_ms: int = 15000
    note_silence_ms: int = 2500
    note_no_speech_ms: int = 6000
    note_max_ms: int = 120000
    key_max_ms: int = 15000


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def after_wake_phrase(text: str, phrases: Sequence[str]) -> str | None:
    """Ce qui suit la derniere phrase de reveil dans `text`, ou None s'il n'y en a pas.

    Tolerant aux variantes de Whisper (« Salut Docteur Vocal ») : une occurrence est le premier mot
    de la phrase suivi, au plus `len(mots)` mots plus loin, d'un mot commencant par son dernier mot.
    Le reste est pris dans le texte d'origine, sans ponctuation ni espaces en tete.
    """
    words = [(_fold(m.group()), m.end()) for m in re.finditer(r"\w+", text)]
    end: int | None = None
    for phrase in phrases:
        parts = _fold(phrase).split()
        if not parts:
            continue
        for i, (word, _) in enumerate(words):
            if word != parts[0]:
                continue
            for j in range(i + 1, min(i + len(parts) + 1, len(words))):
                if words[j][0].startswith(parts[-1]):
                    if end is None or words[j][1] > end:
                        end = words[j][1]
                    break
    if end is None:
        return None
    return re.sub(r"^[^\w]+", "", text[end:])


class Ears:
    """Seul proprietaire du flux micro : les trames vont a l'ecouteur actif, sinon au detecteur de reveil.

    Rien n'est capture ni transcrit hors d'un ecouteur actif.
    """

    def __init__(
        self,
        frames: AsyncIterator[np.ndarray],
        transcribe: Callable[[np.ndarray], str],
        is_speech_factory: Callable[[], Callable[[np.ndarray], bool]],
        captures_dir: Path | None = None,
    ) -> None:
        """`captures_dir` (diagnostic, DEBUG seulement) : chaque ecoute y est gardee en WAV."""
        self._captures_dir = captures_dir
        self._frames = frames
        self._transcribe = transcribe
        self._is_speech_factory = is_speech_factory
        self._queue: asyncio.Queue[np.ndarray | None] | None = None
        self._lock = asyncio.Lock()
        self._closed = False
        self.last_audio: np.ndarray | None = None  # audio de la derniere ecoute (journal des commandes)
        self.last_stt_ms: int | None = None

    async def pump(self, on_frame: Callable[[np.ndarray, bool], None]) -> None:
        """`on_frame(trame, ecoute_en_cours)` voit chaque trame, meme celles qui vont a l'ecouteur."""
        try:
            async for frame in self._frames:
                queue = self._queue
                if queue is not None:
                    queue.put_nowait(frame)
                on_frame(frame, queue is not None)
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
        start = time.perf_counter()
        text = await asyncio.to_thread(self._transcribe, audio)
        self.last_stt_ms = round((time.perf_counter() - start) * 1000)
        log.debug("transcription : %s", text)
        return text.strip() or None

    async def listen(self, silence_ms: int, no_speech_timeout_ms: int, max_ms: int) -> str | None:
        async with self._lock:
            self.last_audio, self.last_stt_ms = None, None
            queue = self._open()
            heard: list[np.ndarray] = []

            async def tee() -> AsyncIterator[np.ndarray]:
                async for frame in self._drain(queue):
                    heard.append(frame)
                    yield frame

            try:
                audio = await capture_utterance(
                    tee(), silence_ms, no_speech_timeout_ms, max_ms, is_speech=self._is_speech_factory())
            finally:
                self._queue = None
            self._keep_capture(heard)
            if audio is None:
                peak = max((int(np.abs(f).max()) for f in heard), default=0)
                log.info("aucune parole apres l'ecoute (%d ms, crete %d/32767)", len(heard) * FRAME_MS, peak)
                return None
            self.last_audio = audio
            return await self._text(audio)

    def _keep_capture(self, frames: list[np.ndarray]) -> None:
        if self._captures_dir is None or not frames:
            return
        try:
            self._captures_dir.mkdir(parents=True, exist_ok=True)
            path = self._captures_dir / f"{datetime.now():%Y-%m-%d_%H-%M-%S-%f}.wav"
            with wave.open(str(path), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(SAMPLE_RATE)
                w.writeframes(np.concatenate(frames).astype(np.int16).tobytes())
            for old in sorted(self._captures_dir.glob("*.wav"))[:-_KEPT_CAPTURES]:
                old.unlink()
        except OSError:
            log.exception("capture de diagnostic impossible")

    async def record_while(self, held: Callable[[], bool], max_ms: int, min_ms: int = 300) -> str | None:
        """Enregistre tant que `held()` est vrai (verifie a chaque trame), plus 2 trames de traine."""
        async with self._lock:
            self.last_audio, self.last_stt_ms = None, None
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
            self.last_audio = np.concatenate(frames)
            return await self._text(self.last_audio)

    async def wait_for_cancel(self, seconds: float) -> bool:
        text = await self.listen(silence_ms=700, no_speech_timeout_ms=int(seconds * 1000), max_ms=5000)
        return text is not None and "annule" in _fold(text)


class Assistant:
    """Boucle principale : reveil, son, capture, parse, action en tache de fond, son de resultat.

    Redire le mot de reveil (ou rappuyer sur la touche) pendant l'ecoute ou la transcription
    d'une commande l'abandonne et en ecoute une nouvelle. Avec `wake_phrases` (mode vocal), le mot de
    reveil dit en pleine phrase n'interrompt plus l'enregistrement : apres transcription, on garde ce
    qui suit la derniere phrase de reveil retrouvee (rien apres : on reecoute), et a defaut toute la
    phrase (le nom peut faire partie de la commande). Pendant la transcription, il relance toujours.
    """

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
        command_log: Callable[..., None] | None = None,
        event_log: Callable[..., None] | None = None,
        wake_phrases: Sequence[str] = (),
    ) -> None:
        self._ears = ears
        self._detector = detector
        self._capture = capture_command
        self._parse = parse
        self._catalogue = catalogue
        self._player = player
        self._speaker = speaker  # jamais utilise pour repondre : pas de voix par defaut
        self._notify = notify
        self._command_log = command_log
        self._event_log = event_log
        self._wake_phrases = tuple(wake_phrases)
        self._waking = False
        self._rewoke = False  # reveil entendu pendant l'enregistrement, a verifier apres transcription
        self._restart = asyncio.Event()
        self._tasks: set[asyncio.Task] = set()

    async def run(self) -> None:
        await self._ears.pump(self._on_frame)

    def _spawn(self, coro: Coroutine[Any, Any, None]) -> None:
        task = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(task)  # reference forte jusqu'a la fin
        task.add_done_callback(self._tasks.discard)

    def _on_frame(self, frame: np.ndarray, listening: bool = False) -> None:
        if listening and not self._waking:
            return  # une action ecoute (note, question de Claude) : le mot de reveil n'y fait rien
        try:
            woke = self._detector.process(frame)
        except Exception:
            log.exception("detecteur de reveil en erreur")
            return
        if not woke:
            return
        if self._waking:
            if listening and self._wake_phrases:
                if not self._rewoke:
                    log.info("reveil en pleine phrase : verification apres transcription")
                self._rewoke = True
            else:
                self._restart.set()
        else:
            self._waking = True
            self._spawn(self._on_wake())

    async def _capture_or_restart(self) -> tuple[str | None, bool]:
        """(texte, False) ; ou (None, True) si le mot de reveil revient avant la fin."""
        self._restart.clear()
        self._rewoke = False
        capture = asyncio.ensure_future(self._capture())
        restart = asyncio.ensure_future(self._restart.wait())
        try:
            done, _ = await asyncio.wait({capture, restart}, return_when=asyncio.FIRST_COMPLETED)
        except BaseException:
            capture.cancel()
            raise
        finally:
            restart.cancel()
        if capture in done:
            return capture.result(), False
        capture.cancel()  # une transcription deja lancee finit dans son thread, ignoree
        await asyncio.wait({capture})  # libere l'ecoute avant d'en ouvrir une autre
        if not capture.cancelled() and capture.exception() is not None:
            log.debug("commande abandonnee en erreur : %r", capture.exception())
        return None, True

    async def _on_wake(self) -> None:
        try:
            self._player.play("wake")
            while True:
                text, restarted = await self._capture_or_restart()
                if not restarted and text is not None and self._rewoke:
                    rest = after_wake_phrase(text, self._wake_phrases)
                    if rest is None:
                        log.info("reveil en pleine phrase ignore")
                    elif rest:
                        text = rest
                    else:
                        restarted = True
                if not restarted:
                    break
                log.info("commande recommencee")
                self._player.play("wake")
            if text is None:
                await self._journal_event("no_speech")
                return  # faux reveil : retour en veille, sans son
            # copie tout de suite : une action Discord reecoute plus tard et ecraserait ces attributs
            audio, stt_ms = self._ears.last_audio, self._ears.last_stt_ms
            intent = self._parse(text)
            if intent is None:
                log.info("commande non comprise")
                await self._journal(text, None, None, audio, stt_ms, None)
                self._player.play("failure")
                return
            self._spawn(self._run_action(intent, text, audio, stt_ms))
        except Exception:
            log.exception("echec pendant le traitement d'un reveil")
        finally:
            self._waking = False

    async def _journal(self, text: str, intent: Intent | None, ok: bool | None, audio: np.ndarray | None,
                       stt_ms: int | None, action_ms: int | None, reply: str | None = None) -> None:
        if self._command_log is None:
            return
        extra = {"reply": reply} if reply is not None else {}
        try:
            await asyncio.to_thread(self._command_log, text, intent, ok, audio, stt_ms, action_ms, **extra)
        except Exception:
            log.exception("journal des commandes en erreur")

    async def _journal_event(self, kind: str) -> None:
        if self._event_log is None:
            return
        try:
            await asyncio.to_thread(self._event_log, kind)
        except Exception:
            log.exception("journal des evenements en erreur")

    async def _run_action(self, intent: Intent, text: str = "", audio: np.ndarray | None = None,
                          stt_ms: int | None = None) -> None:
        start = time.perf_counter()
        try:
            outcome = await self._catalogue.run(intent)
        except Exception:
            log.exception("action %s en erreur", intent.action)
            outcome = Outcome(False)
        action_ms = round((time.perf_counter() - start) * 1000)
        await self._journal(text, intent, outcome.ok, audio, stt_ms, action_ms, outcome.speak)
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


def register_claude(catalogue: Catalogue, voice: ClaudeVoice | None) -> None:
    """Facultatif : sans Claude Code (voice is None), aucune action Claude n'est enregistree."""
    if voice is None:
        return

    async def prompt(intent: Intent) -> Outcome:
        return Outcome(await voice.prompt(intent.args.get("project", ""), intent.args["prompt"]))

    async def proceed(intent: Intent) -> Outcome:
        return Outcome(await voice.proceed(intent.args["prompt"]))

    async def stop(_: Intent) -> Outcome:
        return Outcome(await voice.stop())

    async def import_all(_: Intent) -> Outcome:
        return Outcome(voice.import_all())

    catalogue.register("claude.prompt", prompt)
    catalogue.register("claude.continue", proceed)
    catalogue.register("claude.stop", stop)
    catalogue.register("claude.import", import_all)
