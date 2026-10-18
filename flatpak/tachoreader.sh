#!/bin/sh
# Stable entry point: the frozen bundle must be started from its own directory
# so PyInstaller can locate the rest of dist/TachoReader (_internal/).
exec /app/tachoreader/TachoReader "$@"
