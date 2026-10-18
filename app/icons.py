"""Interface icons from the commissioned set (``assets/icons/``).

The interface used to draw its icons with emoji. An emoji is rendered by
whichever font the operating system happens to pick, so the same build showed a
thin grey outline on one machine, a full-colour cartoon on another and an empty
box on a third. The replacement is a monochrome PNG set, drawn once by a
designer and shipped with the application (``assets/icons/README.md`` is the
designer's own note on it).

Three things this module must get right, all of them learned failures:

* **The cache is not an optimisation, it is a correctness requirement.**
  Tkinter destroys a ``PhotoImage`` as soon as no Python object references it,
  and a destroyed image renders as *nothing* — the row goes blank, no error is
  raised. :data:`_CACHE` keeps every decoded image alive for as long as its
  window lives.
* **A missing icon must never take the window down.** :func:`icon` returns
  ``None`` for a name or size that is not in the set, which every widget option
  accepts as "no image".
* **An image belongs to one Tcl interpreter.** A ``PhotoImage`` lives in the
  interpreter of the root that created it; handing it to a widget of another
  interpreter raises ``TclError: image "pyimageN" doesn't exist``. The
  application rebuilds its window on a language switch, so the cache is kept
  per interpreter (:func:`icon` takes the widget it is for as ``master``) and
  the entries of a window that no longer exists are dropped.

Importing this module needs no Tk root (icons are decoded lazily on first use).
Creating one *does* need a root: without one Tkinter raises, and the raise is
allowed to propagate — caching a broken image would be worse than the error.
"""
import os
import sys

import tkinter as tk

#: Sizes the set is delivered in (``assets/icons/png/<size>/<name>.png``).
#: 16 px is the tree and the inline markers, 20 px the toolbar buttons.
SIZES = (16, 20, 24, 32, 40, 48)

#: ``(interpreter id, name, size) -> tk.PhotoImage``. Every image the UI asks
#: for stays referenced here for as long as its window lives (see the module
#: docstring), which is what stops Tkinter from collecting it.
_CACHE: "dict[tuple[int, str, int], tk.PhotoImage]" = {}

#: ``interpreter id -> interpreter``. Holding the interpreter keeps its ``id()``
#: unique while the cache refers to it, so a stale key can never match an image
#: that belongs to a different (already destroyed) window.
_INTERPRETERS: "dict[int, object]" = {}

#: The interpreter the previous lookup used: a change means a window was
#: rebuilt, which is the moment to sweep the dead one's images.
_LAST_INTERPRETER_ID = None


def icons_dir():
    """Directory holding the ``png/`` and ``svg/`` trees.

    Resolved the way :mod:`app.i18n` resolves ``locale/``: relative to the
    package, never to the current working directory, and from the ``_MEIPASS``
    extraction root when the application is frozen (see ``build.spec``) so the
    set is found however the bundle is launched.
    """
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "assets", "icons")


def icon_path(name, size=16):
    """Path of *name* at *size* px, whether or not the file exists."""
    return os.path.join(icons_dir(), "png", str(size), f"{name}.png")


def names(size=16):
    """Icon names delivered at *size*, sorted (empty when the set is absent)."""
    try:
        entries = os.listdir(os.path.join(icons_dir(), "png", str(size)))
    except OSError:
        return []
    return sorted(entry[:-4] for entry in entries if entry.endswith(".png"))


def _interpreter(master):
    """The Tk interpreter *master* belongs to (``None`` when there is no root).

    ``master`` is any widget or root; without one the default root is used,
    which is what Tkinter itself does for a bare ``PhotoImage(file=...)``.
    """
    if master is None:
        master = getattr(tk, "_default_root", None)
    return getattr(master, "tk", None)


def _alive(interpreter):
    """True while *interpreter* still has a main window to draw its images in.

    Destroying a ``Tk`` window does not delete the Tcl interpreter object
    (CPython frees that with the Python object), so "is the interpreter still
    callable" answers yes for a closed window. What the images die with is the
    *root window*, hence the question asked here.
    """
    try:
        return str(interpreter.call("winfo", "exists", ".")) not in ("", "0")
    except Exception:
        return False


def _drop_dead_windows():
    """Forget the images of windows that have been destroyed.

    A language switch destroys the window and builds a new one, and the images
    of the old interpreter died with it. They are useless — and keeping them
    would leak one entry per icon per switch.
    """
    for interpreter_id, interpreter in list(_INTERPRETERS.items()):
        if _alive(interpreter):
            continue
        del _INTERPRETERS[interpreter_id]
        for key in [key for key in _CACHE if key[0] == interpreter_id]:
            del _CACHE[key]


def icon(name, size=16, master=None):
    """The ``PhotoImage`` for *name* at *size* px, or ``None`` if missing.

    ``None`` is what a widget option wants when there is no image, so a gap in
    the set costs a blank icon, never a traceback.

    *master* is the widget the image is for: the image is created in that
    widget's interpreter and cached with it, so it can never be handed to a
    window it does not belong to (see the module docstring).
    """
    global _LAST_INTERPRETER_ID
    interpreter = _interpreter(master)
    interpreter_id = id(interpreter)
    if interpreter_id != _LAST_INTERPRETER_ID:
        # A window was rebuilt: drop what the previous one left behind, whether
        # or not this call needs a new image.
        _LAST_INTERPRETER_ID = interpreter_id
        _drop_dead_windows()
    key = (interpreter_id, name, size)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    filename = icon_path(name, size)
    if not os.path.isfile(filename):
        return None
    # Needs a Tk root: without one Tkinter raises here, and nothing is cached
    # (the raise happens before the assignments below), so a later call with a
    # real root still decodes the image instead of re-using a broken entry.
    image = tk.PhotoImage(file=filename, master=master)
    _drop_dead_windows()
    _INTERPRETERS[id(interpreter)] = interpreter
    _CACHE[key] = image
    return image
