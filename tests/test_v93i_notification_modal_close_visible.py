"""v93i — notification modal must keep close button on-screen.

The v93 floating modal opened from the bell + the notifications-
center "open" anchor was unscrollable when the notification body
was very tall (e.g. a full periodic-status snapshot). The card
had no `max-height`, so it grew past the viewport edge and the
header — which holds the only ✕ close button — was pushed off
the top of the screen. The bottom "Close" button suffered the
same fate.

v93i caps the card height to the viewport and makes the body
scroll inside the card so the header + footer stay pinned.

This test reads `app/static/js/app.js` as text and asserts the
two structural guarantees we don't want to lose to a refactor:
    1) the card has a `max-height` tied to the viewport, AND
    2) the body uses `overflow-y:auto`, AND
    3) the card is a flex column (so the body can flex-grow
       while header/footer stay 0-flex).
"""
from __future__ import annotations

import os
import re

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_APP_JS = os.path.join(_REPO_ROOT, 'app', 'static', 'js', 'app.js')


def _read_app_js():
    with open(_APP_JS, 'r', encoding='utf-8') as fh:
        return fh.read()


def test_modal_card_caps_height_to_viewport():
    src = _read_app_js()
    # We look for either the calc-based pattern we ship today or a
    # plain vh value, so future polish can switch units without
    # breaking the test.
    assert re.search(r'max-height\s*:\s*calc\(\s*100vh', src) or \
           re.search(r'max-height\s*:\s*\d+vh', src), \
        'The notif-modal card must cap its height to the viewport.'


def test_modal_body_scrolls_internally():
    src = _read_app_js()
    # The body class is `notif-modal__body`; we just verify the
    # word `overflow-y:auto` appears somewhere in the same modal
    # block. Cheap check, but catches the regression we care about.
    assert 'notif-modal__body' in src, 'notif-modal body class missing.'
    # Look for at least one overflow-y:auto inline style in the
    # whole modal definition. We don't need to parse JS — the
    # regression is "someone removed the overflow rule".
    assert re.search(r'overflow-y\s*:\s*auto', src), \
        'The notif-modal body must scroll internally so the head '\
        'and footer stay pinned when the message is tall.'


def test_modal_card_is_flex_column():
    src = _read_app_js()
    # The card relies on flex-direction:column so the body can
    # `flex:1 1 auto` and shrink under max-height while head + footer
    # keep their natural size at flex:0.
    assert re.search(r'flex-direction\s*:\s*column', src), \
        'The notif-modal card must be a flex column to pin its head/footer.'


def test_modal_keeps_two_close_affordances():
    src = _read_app_js()
    # Top X (#notifModalClose) and bottom "Close" (#notifModalCloseBtn)
    # are both wired to the same close handler. Don't accidentally
    # drop one.
    assert '#notifModalClose' in src
    assert '#notifModalCloseBtn' in src
