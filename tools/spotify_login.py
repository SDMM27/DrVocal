"""Autorise Spotify une fois, avant d'utiliser la voix (le jeton est garde dans .spotify-cache).

    uv run python tools/spotify_login.py

Le navigateur s'ouvre sur la page d'autorisation Spotify ; ensuite aucun ordre vocal n'ouvre de page.
Un jeton garde avec d'anciennes permissions est rejete par spotipy (scopes insuffisants) : l'autorisation est redemandee.
"""
from __future__ import annotations

from pathlib import Path

from drvocal.__main__ import load_config
from drvocal.actions_spotify import Library, build_client

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    settings = load_config(ROOT)
    if not settings.spotify_client_id:
        raise SystemExit("spotify_client_id absent de secrets.toml (voir README, section Spotify).")
    client = build_client(settings.spotify_client_id, ROOT / ".spotify-cache")
    devices = client.devices().get("devices", [])
    print("Spotify autorise. Appareils vus :", ", ".join(d["name"] for d in devices) or "aucun (normal si l'application est fermee)")
    entries = Library(client).entries()
    print(f"Bibliotheque chargee : {sum(u.startswith('spotify:artist:') for _, u in entries)} artistes, "
          f"{sum(u.startswith('spotify:playlist:') for _, u in entries)} playlists, "
          f"{len({u for _, u in entries if u.startswith('spotify:track:')})} titres.")


if __name__ == "__main__":
    main()
