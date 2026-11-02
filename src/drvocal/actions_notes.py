"""Sauvegarde d'une note dictee dans un nouveau fichier .txt date."""
from datetime import datetime
from pathlib import Path


def save_note(text: str, notes_dir: Path, now: datetime) -> Path:
    """Ecrit `text` tel quel dans un nouveau fichier ; n'ecrase jamais une note existante."""
    notes_dir.mkdir(parents=True, exist_ok=True)
    stem = now.strftime("%Y-%m-%d_%H-%M-%S")
    n = 1
    while True:
        name = f"{stem}.txt" if n == 1 else f"{stem}-{n}.txt"
        path = notes_dir / name
        try:
            with path.open("x", encoding="utf-8", newline="") as f:
                f.write(text)
            return path
        except FileExistsError:
            n += 1
