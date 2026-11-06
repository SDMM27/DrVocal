import json
import re
from pathlib import Path

import drvocal.screen as screen_mod
from drvocal.claude_policy import Reply
from drvocal.claude_session import SessionEvent
from drvocal.screen import Monitor, SecondScreen, parse_pending, render_event, select_monitor

MONITORS = [Monitor(0, 0, 1920, 1080), Monitor(1920, 0, 1280, 1024)]


def test_events_are_escaped_as_html():
    evil = '<img src=x onerror="alert(1)"> & <script>x</script>'
    for kind in ("text", "tool", "done", "error"):
        html = render_event(SessionEvent(kind, evil))
        assert "<img" not in html and "<script" not in html
        assert "&lt;img" in html and "&amp;" in html and "&quot;" in html


def test_pending_request_exposes_approve_and_reject():
    html = render_event(SessionEvent("pending", "p3: Bash: rm -rf <dir>"))
    assert 'data-id="p3"' in html
    assert 'data-action="approve"' in html and "Autoriser" in html
    assert 'data-action="reject"' in html and "Refuser" in html
    assert "Bash: rm -rf &lt;dir&gt;" in html
    assert "onclick" not in html  # aucun JS en ligne


def test_malformed_pending_has_no_buttons():
    html = render_event(SessionEvent("pending", '"><b>x</b>'))
    assert "data-action" not in html and "<b>" not in html
    assert parse_pending("p12: ok") == ("p12", "ok")
    assert parse_pending("pX: ok") is None
    assert parse_pending('p1"><x: y') is None


def test_missing_screen_never_falls_back_to_primary():
    assert select_monitor(1, MONITORS) == MONITORS[1]
    for bad in (5, -1, 99):
        assert select_monitor(bad, MONITORS) is None
    assert select_monitor(0, []) is None


class FakeWindow:
    def __init__(self):
        self.calls = []

    def evaluate_js(self, code):
        self.calls.append(code)


def make_screen():
    s = SecondScreen(1)
    s._window = FakeWindow()
    s._ready = True
    got = []
    s.on_decision(lambda i, r: got.append((i, r)))
    return s, got


def test_decision_only_for_pending_id_and_only_once():
    s, got = make_screen()
    s.push(SessionEvent("pending", "p1: Bash: ls"))
    s._bridge.decide("p9", "approve")  # inconnu
    s._bridge.decide("p1", "nimporte")  # action invalide
    assert got == []
    s._bridge.decide("p1", "approve")
    s._bridge.decide("p1", "reject")  # deuxieme clic
    s._bridge.decide("p1", "approve")
    assert got == [("p1", Reply.APPROVE)]


def test_reject_and_non_pending_events_do_not_create_decisions():
    s, got = make_screen()
    s.push(SessionEvent("text", "p2: salut"))
    s.push(SessionEvent("pending", "p2: x"))
    s._bridge.decide("p2", "reject")
    assert got == [("p2", Reply.REJECT)]
    s._bridge.decide(123, "approve")  # type inattendu
    assert got == [("p2", Reply.REJECT)]


def test_push_passes_data_as_json_not_concatenated_html():
    s, _ = make_screen()
    evil = "';alert(1);// </script>"
    s.push(SessionEvent("text", evil))
    code = s._window.calls[-1]
    assert code.startswith("addEvent(") and code.endswith(")")
    payload = json.loads(code[len("addEvent("):-1])
    assert "alert(1)" in payload["html"] and " " not in code
    assert "<script" not in payload["html"]


def test_events_pushed_before_window_ready_are_replayed():
    s = SecondScreen(0)
    s.push(SessionEvent("text", "avant"))
    s._window = FakeWindow()
    s._on_loaded()
    assert any("avant" in c for c in s._window.calls)


def test_page_has_restrictive_csp_and_no_remote_resources():
    html = (Path(screen_mod.__file__).parent / "screen.html").read_text(encoding="utf-8")
    csp = re.search(r'Content-Security-Policy"\s+content="([^"]+)"', html).group(1)
    assert "default-src 'none'" in csp and "connect-src 'none'" in csp
    assert "unsafe-inline" not in csp.split("script-src")[1].split(";")[0]
    assert not re.search(r'(src|href)="https?://', html)
    assert "isTrusted" in html and "innerHTML" in html


def test_question_pending_uses_after_game_label():
    html = render_event(SessionEvent("pending", "p4: Quel nom ?", question=True))
    assert "Répondre après la partie" in html and ">Autoriser<" not in html
    assert "Autoriser" in render_event(SessionEvent("pending", "p5: Bash: ls"))


def test_unresolved_pending_is_never_evicted_by_text_events():
    s, got = make_screen()
    s.push(SessionEvent("pending", "p1: Bash: ls"))
    for i in range(500):
        s.push(SessionEvent("text", f"t{i}"))
    assert len(s._history) <= 200
    assert any(pid == "p1" for _, pid in s._history)
    s._window.calls.clear()
    s._ready = False
    s._on_loaded()
    assert any("ev pending" in c and "data-id" in c and "p1" in c for c in s._window.calls)


def test_resolved_pending_can_be_evicted_later():
    s, got = make_screen()
    s.push(SessionEvent("pending", "p1: Bash: ls"))
    s._bridge.decide("p1", "approve")
    for i in range(300):
        s.push(SessionEvent("text", f"t{i}"))
    assert not any(pid == "p1" for _, pid in s._history)


def test_page_never_removes_unresolved_pending_and_has_close_button():
    html = (Path(screen_mod.__file__).parent / "screen.html").read_text(encoding="utf-8")
    assert 'id="close"' in html and "hide_window" in html
    assert 'classList.contains("resolved")' in html


def test_window_is_not_topmost():
    source = Path(screen_mod.__file__).read_text(encoding="utf-8")
    assert "on_top" not in source and "TOPMOST" not in source


def test_show_does_nothing_when_requested_monitor_is_missing(monkeypatch):
    placed = []
    monkeypatch.setattr(screen_mod, "_place_and_show", lambda hwnd, mon: placed.append((hwnd, mon)))
    s = SecondScreen(1, monitors=lambda: [MONITORS[0]])
    s._hwnd = 42
    assert s.show() is False and placed == []
    s.push(SessionEvent("text", "reste en memoire"))
    assert len(s._history) == 1


def test_show_places_window_on_requested_monitor(monkeypatch):
    placed = []
    monkeypatch.setattr(screen_mod, "_place_and_show", lambda hwnd, mon: placed.append((hwnd, mon)))
    s = SecondScreen(1, monitors=lambda: MONITORS)
    s._hwnd = 42
    assert s.show() is True and placed == [(42, MONITORS[1])]


def test_show_when_monitor_lookup_fails_stays_hidden(monkeypatch):
    placed = []
    monkeypatch.setattr(screen_mod, "_place_and_show", lambda hwnd, mon: placed.append(mon))

    def boom():
        raise RuntimeError("pas d'ecran")

    s = SecondScreen(0, monitors=boom)
    s._hwnd = 42
    assert s.show() is False and placed == []


def test_close_button_bridge_hides_window(monkeypatch):
    hidden = []
    monkeypatch.setattr(screen_mod, "_hide", hidden.append)
    s = SecondScreen(0, monitors=lambda: MONITORS)
    s._hwnd = 7
    s._bridge.hide_window()
    assert hidden == [7] and s._wanted_visible is False
