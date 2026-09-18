"""Switching views in a test without racing the app's own startup.

``loadView`` is async: it fetches ``/static/views/<name>.html`` and then writes
``#view-container`` (``static/js/app.js:351``).  The page itself kicks off
``loadView("grade")`` from its DOMContentLoaded handler (``app.js:137``), so a
test that calls ``page.evaluate("window.loadView('analytics')")`` straight after
``goto`` leaves two fetches in flight for the same container.  Whichever
resolves last wins.  When "grade" wins, the requested view is never in the DOM
and the caller's ``wait_for`` times out with nothing useful to say.

That is what makes the suite fail roughly one run in three, on a different test
each time, and pass every time when a test is run alone -- less load, so the
startup fetch reliably finishes first.  It is a race, not a slow machine: a
longer timeout does not fix it.

Waiting for the startup view to land before switching removes the overlap.
"""

from playwright.sync_api import Page

# setActiveView records the view on <body> once loadView has written the
# container, so this is true only after that first render has completed.
_STARTUP_VIEW_READY = 'body[data-active-view="grade"]'


def switch_to_view(page: Page, name: str, timeout: int = 8_000) -> None:
    """Load *name*, once the app's own initial view has finished loading."""
    page.wait_for_selector(_STARTUP_VIEW_READY, timeout=timeout)
    page.evaluate(f"window.loadView('{name}')")
