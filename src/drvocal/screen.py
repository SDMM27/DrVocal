"""Fenetre du deuxieme ecran : progression de Claude Code, sans jamais prendre le focus.

Tout le texte des evenements vient de Claude ou de commandes : il est donc non fiable.
Il est echappe cote Python et transmis a la page en JSON, jamais concatene dans du JS.
Un clic Autoriser/Refuser passe par le pont JS de pywebview ; seul un identifiant
actuellement en attente est accepte, et une seule fois.

pywebview exige que sa boucle graphique tourne dans le thread principal :
`SecondScreen.run()` bloque donc et doit etre appele depuis le thread principal.
`show()`, `push()` et `hide()` peuvent ensuite etre appeles depuis n'importe quel thread.
"""
import base64
import hashlib
import html
import json
import re
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from drvocal.claude_policy import Reply
from drvocal.claude_session import SessionEvent

_PAGE = Path(__file__).with_name("screen.html")
_PENDING_RE = re.compile(r"p\d+")
_ACTIONS = {"approve": Reply.APPROVE, "reject": Reply.REJECT}
_MAX_EVENTS = 200


@dataclass(frozen=True)
class Monitor:
    x: int
    y: int
    width: int
    height: int


def select_monitor(index: int, monitors: list[Monitor]) -> Monitor | None:
    """Ecran demande, ou None s'il n'existe pas : jamais de repli sur l'ecran principal,
    car la fenetre pourrait alors recouvrir le jeu."""
    if 0 <= index < len(monitors):
        return monitors[index]
    return None


def _current_monitors() -> list[Monitor]:
    import webview  # import tardif : lourd, et inutile pour les tests

    return [Monitor(s.x, s.y, s.width, s.height) for s in webview.screens]


def parse_pending(text: str) -> tuple[str, str] | None:
    """Decoupe "pN: resume" ; None si le format n'est pas celui attendu."""
    pending_id, sep, summary = text.partition(": ")
    if not sep or not _PENDING_RE.fullmatch(pending_id):
        return None
    return pending_id, summary


def render_event(event: SessionEvent) -> str:
    """HTML d'un evenement ; tout le texte variable est echappe."""
    kind = event.kind if event.kind in ("text", "tool", "pending", "done", "error") else "text"
    if kind == "pending":
        parsed = parse_pending(event.text)
        if parsed:
            pending_id, summary = parsed
            label = "Répondre après la partie" if event.question else "Autoriser"
            return (
                f'<div class="ev pending" data-id="{html.escape(pending_id)}">'
                f"<div>{html.escape(summary)}</div>"
                '<div class="actions">'
                f'<button type="button" data-action="approve">{label}</button>'
                '<button type="button" data-action="reject">Refuser</button>'
                "</div></div>"
            )
        kind = "text"  # format inattendu : affiche, sans boutons
    return f'<div class="ev {kind}">{html.escape(event.text)}</div>'


def _page_with_hash() -> str:
    """Page avec le hash du script inline dans la CSP (aucun 'unsafe-inline' pour les scripts)."""
    page = _PAGE.read_text(encoding="utf-8")
    script = re.search(r"<script>(.*?)</script>", page, re.DOTALL).group(1)
    digest = base64.b64encode(hashlib.sha256(script.encode("utf-8")).digest()).decode()
    return page.replace("__SCRIPT_HASH__", digest)


class _Bridge:
    """Seul objet expose a la page (pywebview expose ses methodes publiques)."""

    def __init__(self, screen: "SecondScreen") -> None:
        self._screen = screen

    def decide(self, pending_id, action) -> None:
        self._screen._decide(pending_id, action)

    def hide_window(self) -> None:
        self._screen.hide()


class SecondScreen:
    def __init__(self, screen_index: int, monitors: Callable[[], list[Monitor]] = _current_monitors) -> None:
        self._index = screen_index
        self._monitors = monitors
        self._lock = threading.Lock()
        self._bridge = _Bridge(self)
        self._callback: Callable[[str, Reply], None] | None = None
        self._pending: set[str] = set()
        self._resolved: set[str] = set()
        self._history: list[tuple[str, str | None]] = []  # (html, id d'une demande, sinon None)
        self._window = None
        self._ready = False
        self._wanted_visible = False
        self._hwnd = 0

    def on_decision(self, callback: Callable[[str, Reply], None]) -> None:
        """Appele (depuis un thread de pywebview) avec l'id en attente et la reponse."""
        self._callback = callback

    def push(self, event: SessionEvent) -> None:
        rendered = render_event(event)
        with self._lock:
            pending_id = None
            if event.kind == "pending":
                parsed = parse_pending(event.text)
                if parsed:
                    pending_id = parsed[0]
                    self._pending.add(pending_id)
            self._history.append((rendered, pending_id))
            self._evict()
            self._send("addEvent", {"html": rendered})

    def _evict(self) -> None:
        """Garde _MAX_EVENTS evenements au plus, sans jamais perdre une demande non traitee."""
        while len(self._history) > _MAX_EVENTS:
            for i, (_, pending_id) in enumerate(self._history):
                if pending_id is None or pending_id in self._resolved:
                    del self._history[i]
                    self._resolved.discard(pending_id)
                    break
            else:
                return  # que des demandes en attente : on les garde toutes

    def _decide(self, pending_id, action) -> None:
        reply = _ACTIONS.get(action) if isinstance(action, str) else None
        if reply is None or not isinstance(pending_id, str):
            return
        with self._lock:
            if pending_id not in self._pending:
                return
            self._pending.discard(pending_id)
            self._resolved.add(pending_id)
            self._send("markResolved", {"id": pending_id})
            callback = self._callback
        if callback:
            callback(pending_id, reply)

    def _send(self, function: str, payload: dict) -> None:
        """Appel JS avec une charge utile JSON ; a appeler sous verrou."""
        if not (self._ready and self._window):
            return
        # ensure_ascii (defaut) echappe aussi U+2028/U+2029, qui cassent un litteral JS.
        try:
            self._window.evaluate_js(f"{function}({json.dumps(payload)})")
        except Exception:
            pass  # fenetre en cours de fermeture

    def _on_loaded(self) -> None:
        with self._lock:
            first = not self._ready
            self._ready = True
            if first:
                for rendered, _ in self._history:
                    self._send("addEvent", {"html": rendered})
                for pending_id in self._resolved:
                    self._send("markResolved", {"id": pending_id})
        self._apply_window_style()
        if self._wanted_visible:
            self.show()

    # --- fenetre -------------------------------------------------------

    def run(self) -> None:
        """Cree la fenetre (masquee) et bloque dans la boucle graphique. Thread principal."""
        import webview  # import tardif : lourd, et inutile pour les tests

        # Creee masquee a une position neutre ; l'ecran voulu est choisi a chaque show().
        self._window = webview.create_window(
            "Dr Vocal",
            html=_page_with_hash(),
            js_api=self._bridge,
            width=800, height=600,
            hidden=True, focus=False, frameless=True, easy_drag=False,
        )
        self._window.events.loaded += self._on_loaded
        webview.start()
        self._ready = False
        self._window = None
        self._hwnd = 0

    def show(self) -> bool:
        """Affiche la fenetre sans l'activer, sur l'ecran demande uniquement.

        Si cet ecran n'existe pas (ou ne peut pas etre lu), la fenetre reste masquee : la
        remplacer sur l'ecran principal pourrait recouvrir le jeu. Les evenements
        continuent de s'accumuler et s'affichent au prochain show() reussi.
        """
        try:
            monitor = select_monitor(self._index, self._monitors())
        except Exception:
            monitor = None
        if monitor is None:
            self._wanted_visible = False
            return False
        self._wanted_visible = True
        if self._hwnd:
            _place_and_show(self._hwnd, monitor)
        return True

    def hide(self) -> None:
        self._wanted_visible = False
        if self._hwnd:
            _hide(self._hwnd)

    def close(self) -> None:
        window, self._window = self._window, None
        if window:
            try:
                window.destroy()
            except Exception:
                pass

    def _apply_window_style(self) -> None:
        if self._hwnd or sys.platform != "win32" or not self._window:
            return
        try:
            self._hwnd = int(self._window.native.Handle.ToInt64())
        except Exception:
            return
        _set_noactivate_style(self._hwnd)


# --- Win32 -------------------------------------------------------------

_GWL_EXSTYLE = -20
_WS_EX_NOACTIVATE = 0x08000000
_WS_EX_TOOLWINDOW = 0x00000080  # pas de bouton dans la barre des taches ni dans Alt+Tab
_WS_EX_APPWINDOW = 0x00040000
_SW_HIDE = 0
_SW_SHOWNOACTIVATE = 4
_SWP_NOZORDER, _SWP_NOACTIVATE = 0x4, 0x10


def _user32():
    import ctypes
    from ctypes import wintypes

    u = ctypes.windll.user32
    u.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    u.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    u.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    u.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                               ctypes.c_int, ctypes.c_int, wintypes.UINT]
    return u


def _set_noactivate_style(hwnd: int) -> None:
    u = _user32()
    style = u.GetWindowLongPtrW(hwnd, _GWL_EXSTYLE)
    style = (style | _WS_EX_NOACTIVATE | _WS_EX_TOOLWINDOW) & ~_WS_EX_APPWINDOW
    u.SetWindowLongPtrW(hwnd, _GWL_EXSTYLE, style)


def _place_and_show(hwnd: int, mon: Monitor) -> None:
    """Place la fenetre sur l'ecran voulu puis l'affiche, sans activation ni « toujours au-dessus »."""
    u = _user32()
    u.SetWindowPos(hwnd, None, mon.x, mon.y, mon.width, mon.height, _SWP_NOZORDER | _SWP_NOACTIVATE)
    u.ShowWindow(hwnd, _SW_SHOWNOACTIVATE)


def _hide(hwnd: int) -> None:
    _user32().ShowWindow(hwnd, _SW_HIDE)
