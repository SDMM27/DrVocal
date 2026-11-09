import json
import re
from pathlib import Path

import drvocal.screen as screen_mod
from drvocal.events import SessionEvent
from drvocal.screen import Monitor, SecondScreen, render_event, select_monitor

MONITORS = [Monitor(0, 0, 1920, 1080), Monitor(1920, 0, 1280, 1024)]


def test_events_are_escaped_as_html():
    evil = '<img src=x onerror="alert(1)"> & <script>x</script>'
    for kind in ("text", "done", "error"):
        html = render_event(SessionEvent(kind, evil))
        assert "<img" not in html and "<script" not in html
        assert "&lt;img" in html and "&amp;" in html and "&quot;" in html


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
    return s


def test_push_passes_data_as_json_not_concatenated_html():
    s = make_screen()
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


def test_unknown_kind_is_rendered_as_text():
    assert 'class="ev text"' in render_event(SessionEvent("pending", "x"))


def test_history_keeps_only_the_latest_events():
    s = make_screen()
    for i in range(300):
        s.push(SessionEvent("text", f"t{i}"))
    assert len(s._history) == 200 and "t299" in s._history[-1] and "t100" in s._history[0]


def test_page_has_close_button_and_no_decision_buttons():
    html = (Path(screen_mod.__file__).parent / "screen.html").read_text(encoding="utf-8")
    assert 'id="close"' in html and "hide_window" in html
    assert "data-action" not in html and "decide" not in html and html.count("<script>") == 1
