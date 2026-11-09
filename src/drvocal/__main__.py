"""Point d'entree : `python -m drvocal`."""
from __future__ import annotations

import asyncio
import io
import logging
import os
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

from drvocal.config import ConfigError, Settings, load_settings
from drvocal.secrets_store import SecretStore
from drvocal.storage import (
    config_dir,
    data_dir,
    default_store,
    documents_dir,
    legacy_root,
    logs_dir,
    migrate_legacy,
    resolve_data_path,
)

log = logging.getLogger("drvocal")
QUIET_LOGGERS = ("spotipy", "urllib3", "httpcore", "httpcore2", "httpx", "httpx2", "discord", "asyncio")


def setup_logging() -> Path:
    """Journal fichier tournant (1 Mo x 3). Les transcriptions ne sont ecrites qu'en DEBUG."""
    path = logs_dir() / "drvocal.log"
    handler = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s : %(message)s"))
    level = getattr(logging, os.environ.get("DRVOCAL_LOG_LEVEL", "INFO").upper(), logging.INFO)
    logging.basicConfig(level=level, handlers=[handler], force=True)
    for noisy in QUIET_LOGGERS:  # en DEBUG, spotipy ecrit le jeton d'acces (en-tete Authorization)
        logging.getLogger(noisy).setLevel(max(level, logging.INFO))
    return path


def load_config(directory: Path | None = None, store: SecretStore | None = None) -> Settings:
    """config.toml dans config_dir() et secrets du SecretStore ; config absente : reglages par defaut."""
    path = (directory or config_dir()) / "config.toml"
    if not path.exists():
        log.warning("config.toml absent (%s), reglages par defaut", path)
    return load_settings(path, store if store is not None else default_store(), missing_ok=True)


def _rooted(path: Path) -> Path:
    return resolve_data_path(path, legacy_root())


def migrate_from_checkout(store: SecretStore) -> list[str]:
    """Premier lancement depuis un checkout : importe config, secrets et jeton Spotify vers les dossiers utilisateur."""
    root = legacy_root()
    return migrate_legacy(root, config_dir(), store) if root is not None else []


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
    from drvocal.journal import register_journal

    loop = asyncio.get_running_loop()
    timings = Timings()
    player = SoundPlayer({k: _rooted(v) for k, v in settings.sounds.items()})
    speaker = Speaker(_rooted(settings.tts_voice))
    vad = SileroVAD()

    def fresh_vad():
        vad.reset()  # un seul ecouteur a la fois (verrou de Ears) : on reutilise le modele charge
        return vad

    from drvocal.vocabulary import make_hotwords

    spotify_library: list = []  # rempli par _register_optional, apres la creation du Transcriber

    def spotify_names() -> list[str]:
        return spotify_library[0].vocabulary() if spotify_library else []  # ne bloque jamais sur le reseau

    hotwords = make_hotwords(settings, spotify_names) if settings.stt_hotwords else None
    transcriber = Transcriber(settings.stt_model, settings.stt_device, hotwords=hotwords)
    captures = None
    if log.isEnabledFor(logging.DEBUG):  # diagnostic : ce que le micro a capte apres chaque reveil
        captures = data_dir() / "captures"
    ears = Ears(MicStream().frames(), transcriber.transcribe, fresh_vad, captures)

    command_log = event_log = on_rejected = None
    if settings.command_log:
        from drvocal.command_log import CommandLog

        journal = CommandLog(data_dir() / "commands")
        command_log = journal.record
        event_log = journal.record_event
        on_rejected = lambda score: journal.record_event("wake_rejected", score=round(score, 2))  # noqa: E731

    mode = settings.wake_mode
    models = sorted(_rooted(settings.wake_models_dir).glob("*.onnx")) if mode == "voice" else []
    if mode == "voice" and not models:
        log.error("aucun modele de reveil dans %s, repli sur la touche", _rooted(settings.wake_models_dir))
        mode = "key"
    if mode == "voice":
        from drvocal.audio.vad import speech_confirmer
        from drvocal.audio.wake import WakeDetector

        # Detecteur de parole a part (celui d'Ears sert pendant l'ecoute) ; ne tourne qu'au reveil.
        detector = WakeDetector(models, settings.wake_threshold, confirm=speech_confirmer(),
                                on_rejected=on_rejected)

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
    register_journal(catalogue)
    store = default_store()

    def claude_api_key() -> str | None:
        # Magasin chiffre d'abord ; la variable d'environnement reste un repli de developpement.
        return store.get("claude_api_key") or os.environ.get("ANTHROPIC_API_KEY") or None

    runner = ClaudeRunner(make_event_handler(player, push), make_ask_user(ears, speaker, timings),
                          api_key_provider=claude_api_key, audit_path=logs_dir() / "claude-audit.jsonl")
    register_claude(catalogue, runner, settings, api_key_provider=claude_api_key)
    screen.on_decision(lambda pending_id, reply: asyncio.run_coroutine_threadsafe(
        runner.resolve_pending(pending_id, reply), loop))

    background: set[asyncio.Task] = set()
    library = _register_optional(catalogue, settings, ears, speaker, background, store)
    if library is not None:
        spotify_library.append(library)

    async def preload_stt() -> None:
        try:
            await asyncio.to_thread(transcriber.preload)  # sinon la premiere commande attend ~20 s
        except Exception:
            log.exception("prechargement de la transcription impossible")

    preload = loop.create_task(preload_stt())
    background.add(preload)
    preload.add_done_callback(background.discard)

    assistant = Assistant(ears, detector, capture_command, lambda text: parse(text, settings),
                          catalogue, player, speaker, notify=lambda text: push(SessionEvent("text", text)),
                          command_log=command_log, event_log=event_log)
    try:
        await assistant.run()
    finally:
        for task in background:
            task.cancel()


def _register_optional(catalogue, settings: Settings, ears, speaker, background: set, store: SecretStore):
    """Spotify, Discord, raccourcis : un echec au demarrage est journalise et ignore.

    Renvoie la bibliotheque Spotify (ou None) pour le vocabulaire de transcription.
    """
    library = None
    if settings.spotify_client_id:
        try:
            from drvocal.actions_spotify import SecretStoreCacheHandler, build_client, register_spotify
            from drvocal.spotify_aliases import Aliases

            client = build_client(settings.spotify_client_id, SecretStoreCacheHandler(store))
            library = register_spotify(catalogue, client, aliases=Aliases(data_dir() / "spotify_aliases.json"))
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
    return library


SECRET_NAMES = ("spotify_client_id", "spotify_token", "discord_bot_token", "claude_api_key")


def check(store: SecretStore | None = None) -> int:
    """`--check` : affiche emplacements et presence des secrets (jamais leurs valeurs), ne demarre rien."""
    store = store if store is not None else default_store()
    try:
        settings = load_config(store=store)
    except ConfigError as exc:
        print(f"Configuration invalide : {exc}")
        return 1

    def yes(flag: bool) -> str:
        return "oui" if flag else "non"

    cfg = config_dir() / "config.toml"
    print(f"Configuration : {cfg} ({'trouvée' if cfg.exists() else 'absente, réglages par défaut'})")
    print(f"Données : {data_dir()}")
    print(f"Journaux : {logs_dir()}")
    print(f"Notes : {settings.notes_dir}")
    print(f"Documents : {documents_dir()}")
    print("Secrets :")
    for name in SECRET_NAMES:
        print(f"  {name} : {yes(store.get(name) is not None)}")
    wake = _rooted(settings.wake_models_dir)
    print(f"Modèles de réveil ({wake}) : {yes(wake.is_dir() and any(wake.glob('*.onnx')))}")
    print(f"Voix Piper ({_rooted(settings.tts_voice)}) : {yes(_rooted(settings.tts_voice).exists())}")
    root = legacy_root()
    if root is not None:
        old = [n for n in ("config.toml", "secrets.toml", ".spotify-cache") if (root / n).exists()]
        if old:
            print(f"Anciens fichiers du dépôt à migrer au prochain lancement : {', '.join(old)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if "--check" in args:  # ne migre rien et ne touche ni micro ni fenetre
        for stream in (sys.stdout, sys.stderr):
            if isinstance(stream, io.TextIOWrapper):
                stream.reconfigure(encoding="utf-8", errors="replace")
        return check()
    log_path = setup_logging()
    store = default_store()
    try:
        migrate_from_checkout(store)
        settings = load_config(store=store)
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
