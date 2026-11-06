"""Autorise Spotify une fois, avant d'utiliser la voix (le jeton est garde chiffre dans le SecretStore).

    uv run python tools/spotify_login.py

Le navigateur s'ouvre sur la page d'autorisation Spotify ; ensuite aucun ordre vocal n'ouvre de page.
Un jeton garde avec d'anciennes permissions est rejete par spotipy (scopes insuffisants) : l'autorisation est redemandee.
"""
from __future__ import annotations

from drvocal.__main__ import load_config, migrate_from_checkout
from drvocal.actions_spotify import Library, SecretStoreCacheHandler, build_client
from drvocal.storage import default_store


def main() -> None:
    store = default_store()
    migrate_from_checkout(store)  # importe l'ancien secrets.toml / .spotify-cache si on lance depuis le depot
    settings = load_config(store=store)
    if not settings.spotify_client_id:
        raise SystemExit("spotify_client_id absent du SecretStore (voir README, section Spotify).")
    client = build_client(settings.spotify_client_id, SecretStoreCacheHandler(store))
    devices = client.devices().get("devices", [])
    print("Spotify autorise. Appareils vus :", ", ".join(d["name"] for d in devices) or "aucun (normal si l'application est fermee)")
    entries = Library(client).entries()
    print(f"Bibliotheque chargee : {sum(u.startswith('spotify:artist:') for _, u in entries)} artistes, "
          f"{sum(u.startswith('spotify:playlist:') for _, u in entries)} playlists, "
          f"{len({u for _, u in entries if u.startswith('spotify:track:')})} titres.")


if __name__ == "__main__":
    main()
