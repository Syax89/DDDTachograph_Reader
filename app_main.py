"""Frozen-app entry point (see build.spec).

Routes the headless CI modes (--version / --smoke) through a tracer that
captures any startup failure into the file named by TACHO_SMOKE_LOG: the
windowed Windows bundle has no stdout and must never reach PyInstaller's
modal error dialog, which would block a headless runner forever.
"""
import os
import sys
import traceback


def _trace(line):
    log = os.environ.get("TACHO_SMOKE_LOG")
    if log:
        try:
            with open(log, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass


def main():
    if sys.argv[1:2] in (["--version"], ["--smoke"]):
        _trace("BOOT: entry point reached")
        try:
            import gui_tree
            _trace("IMPORTS OK")
            gui_tree.main()
        except SystemExit:
            raise
        except BaseException:
            _trace("FATAL during startup:\n" + traceback.format_exc())
            sys.exit(1)
    else:
        import gui_tree
        gui_tree.main()


main()
