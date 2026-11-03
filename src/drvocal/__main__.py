"""Point d'entree : `python -m drvocal`."""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import tempfile
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

from drvocal.config import ConfigError, Settings, load_settings

ROOT = Path(__file__).resolve().parent.parent.parent
log = logging.getLogger("drvocal")


def setup_logging() -> Path:
    """Journal fichier tournant (1 Mo x 3). Les transcriptions ne sont ecrites qu'en DEBUG."""
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    path = base / "DrVocal" / "drvocal.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s : %(message)s"))
    level = getattr(logging, os.environ.get("DRVOCAL_LOG_LEVEL", "INFO").upper(), logging.INFO)
    logging.basicConfig(level=level, handlers=[handler], force=True)
    return path


def load_config(root: Path = ROOT) -> Settings:
    """config.toml et secrets.toml a la racine ; config absente : reglages par defaut."""
    config, secrets = root / "config.toml", root / "secrets.toml"
    if config.exists():
        return load_settings(config, secrets)
    log.warning("config.toml absent, reglages par defaut")
    with tempfile.TemporaryDirectory() as tmp:
        empty = Path(tmp) / "config.toml"
        empty.write_text("", encoding="utf-8")
        return load_settings(empty, secrets)


def _rooted(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


async def amain(settings: Settings, screen) -> None:
    from drvocal.actions import Catalogue
    from drvocal.app import (
        Assistant,
        Ears,
        Timings,
        make_ask_user,
        make_event_handler,
        register_claude,
        register_notes,
    )
    from drvocal.audio.mic import MicStream
    from drvocal.audio.push_to_talk import KeyTrigger
    from drvocal.audio.sounds import SoundPlayer
    from drvocal.audio.stt import Transcriber
    from drvocal.audio.tts import Speaker
    from drvocal.audio.vad import SileroVAD
    from drvocal.claude_session import ClaudeRunner, SessionEvent
    from drvocal.intent import parse

    loop = asyncio.get_running_loop()
    timings = Timings()
    player = SoundPlayer({k: _rooted(v) for k, v in settings.sounds.items()})
    speaker = Speaker(_rooted(settings.tts_voice))
    vad = SileroVAD()

    def fresh_vad():
        vad.reset()  # un seul ecouteur a la fois (verrou de Ears) : on reutilise le modele charge
        return vad

    transcriber = Transcriber(settings.stt_model, settings.stt_device)
    ears = Ears(MicStream().frames(), transcriber.transcribe, fresh_vad)

    mode = settings.wake_mode
    models = sorted(_rooted(settings.wake_models_dir).glob("*.onnx")) if mode == "voice" else []
    if mode == "voice" and not models:
        log.error("aucun modele de reveil dans %s, repli sur la touche", _rooted(settings.wake_models_dir))
        mode = "key"
    if mode == "voice":
        from drvocal.audio.wake import WakeDetector

        detector = WakeDetector(models, settings.wake_threshold)

        def capture_command():
            return ears.listen(timings.command_silence_ms, timings.command_no_speech_ms, timings.command_max_ms)
    else:
        trigger = detector = KeyTrigger(settings.push_to_talk_key)

        def capture_command():
            return ears.record_while(trigger.held, timings.key_max_ms)
    log.info("mode de reveil : %s", mode)

    def push(event: SessionEvent) -> None:
        screen.push(event)
        screen.show()  # n'active jamais la fenetre

    catalogue = Catalogue()
    register_notes(catalogue, ears, settings.notes_dir, player, timings)
    runner = ClaudeRunner(make_event_handler(player, push), make_ask_user(ears, speaker, timings))
    register_claude(catalogue, runner, settings)
    screen.on_decision(lambda pending_id, reply: asyncio.run_coroutine_threadsafe(
        runner.resolve_pending(pending_id, reply), loop))

    background: set[asyncio.Task] = set()
    _register_optional(catalogue, settings, ears, speaker, background)

    async def preload_stt() -> None:
        try:
            await asyncio.to_thread(transcriber.preload)  # sinon la premiere commande attend ~20 s
        except Exception:
            log.exception("prechargement de la transcription impossible")

    preload = loop.create_task(preload_stt())
    background.add(preload)
    preload.add_done_callback(background.discard)

    assistant = Assistant(ears, detector, capture_command, lambda text: parse(text, settings),
                          catalogue, player, speaker, notify=lambda text: push(SessionEvent("text", text)))
    try:
        await assistant.run()
    finally:
        for task in background:
            task.cancel()


def _register_optional(catalogue, settings: Settings, ears, speaker, background: set) -> None:
    """Spotify, Discord, raccourcis : un echec au demarrage est journalise et ignore."""
    if settings.spotify_client_id:
        try:
            from drvocal.actions_spotify import build_client, register_spotify

            register_spotify(catalogue, build_client(settings.spotify_client_id, ROOT / ".spotify-cache"))
        except Exception:
            log.exception("Spotify indisponible")
    if settings.discord_bot_token and settings.discord_owner_id:
        try:
            from drvocal.actions_discord import make_client, register_discord, run_bot

            client = make_client()
            register_discord(catalogue, client, settings, speak=speaker.say, wait_cancel=ears.wait_for_cancel,
                             owner_id=settings.discord_owner_id,
                             register_self_voice=not settings.simulated_hotkeys_enabled)

            async def bot() -> None:
                try:
                    await run_bot(settings.discord_bot_token, client)
                except Exception as exc:
                    log.error("bot Discord arrete (%s)", type(exc).__name__)  # jamais le jeton

            task = asyncio.get_running_loop().create_task(bot())
            background.add(task)
            task.add_done_callback(background.discard)
        except Exception:
            log.exception("Discord indisponible")
    if settings.simulated_hotkeys_enabled:
        try:
            from drvocal.actions_hotkeys import register_hotkeys, send_keys

            register_hotkeys(catalogue, send_keys, settings)
        except Exception:
            log.exception("raccourcis clavier indisponibles")


def main() -> int:
    log_path = setup_logging()
    try:
        settings = load_config()
    except ConfigError as exc:
        log.error("configuration invalide : %s", exc)
        return 1
    log.info("demarrage (journal : %s)", log_path)

    from drvocal.screen import SecondScreen

    screen = SecondScreen(settings.second_screen_index)
    loop = asyncio.new_event_loop()
    main_task: list[asyncio.Task] = []

    def worker() -> None:
        asyncio.set_event_loop(loop)
        task = loop.create_task(amain(settings, screen))
        main_task.append(task)
        try:
            loop.run_until_complete(task)
        except asyncio.CancelledError:
            pass
        except Exception:
            log.exception("arret inattendu")
        finally:
            loop.close()
            try:
                screen.close()  # debloque screen.run() si la boucle s'arrete seule
            except Exception:
                log.exception("fermeture de l'ecran impossible")

    thread = threading.Thread(target=worker, name="drvocal-loop", daemon=True)
    thread.start()
    try:
        screen.run()  # bloquant, thread principal
    except KeyboardInterrupt:
        pass
    finally:
        if main_task and not loop.is_closed():
            loop.call_soon_threadsafe(main_task[0].cancel)
        thread.join(timeout=5)
        log.info("arret")
    return 0


if __name__ == "__main__":
    sys.exit(main())
