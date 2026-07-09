# -*- mode: python ; coding: utf-8 -*-
import os
import sys

base_path = os.path.abspath(".")
sys.path.insert(0, base_path)
from core.utils.version import __version__  # noqa: E402 — single version source

# ERCA certificates (needed for signature validation)
certs_path = os.path.join(base_path, "certs")
added_files = []
if os.path.exists(certs_path):
    added_files.append((certs_path, "certs"))

# App icons: .ico/.icns for the executables, one PNG for the Tk window icon.
icons_path = os.path.join(base_path, "AppIcons")
win_icon = os.path.join(icons_path, "icon.ico")
mac_icon = os.path.join(icons_path, "icon.icns")
window_png = os.path.join(icons_path, "Assets.xcassets", "AppIcon.appiconset", "256.png")
if os.path.exists(window_png):
    added_files.append((window_png, "AppIcons"))

# NOTE: core/ must NOT go in datas — PyInstaller collects it automatically
# from hiddenimports; listing it in datas duplicates every module in the
# dist build. reportlab is needed for the PDF export (lazy import in
# export_manager).

# PyInstaller configuration
block_cipher = None

# TACHO_CONSOLE=1 builds a console variant (used by CI to diagnose
# windowed-bundle startup failures, which have no stdout/stderr).
console_build = os.environ.get("TACHO_CONSOLE") == "1"

a = Analysis(
    ['app/frozen.py'],
    pathex=[base_path, os.path.join(base_path, 'core')],
    binaries=[],
    datas=added_files,
    hiddenimports=[
        'tkinter',
        'cryptography',
        'core.crypto.signature',
        'core',
        'core.decoders',
        'core.decoders.primitives',
        'core.decoders.card',
        'core.decoders.g22_card',
        'core.decoders.cert',
        'core.decoders.vu_trep',
        'core.decoders.g2_dispatch',
        'core.parser.deterministic',
        'core.parser.record_array',
        'core.parser.vu_dispatcher',
        'core.parser.g1_walker',
        'core.registry.registry',
        'core.registry.models',
        'core.utils.event_codes',
        'core.utils.logger',
        'core.utils.tag_defs',
        'core.utils.report_format',
        'core.utils.version',
        'core.utils.ber_tlv',
        'core.utils.coverage',
        'core.utils.encoding',
        'core.utils.constants',
        'openpyxl',
        'reportlab',
        'reportlab.lib',
        'reportlab.platypus',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Only heavy third-party libraries the app does NOT use.
        # NB: never exclude stdlib modules (email, html, urllib3, http, ...):
        # cryptography imports them and their absence crashes the frozen
        # executable at startup.
        'scipy', 'sklearn', 'matplotlib', 'cv2',
        'numpy.testing', 'numpy.distutils',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='TachoReader',
    debug=False,
    bootloader_ignore_signals=False,
    # Never strip on Windows: binutils strip (present on CI runners via the
    # Git/MinGW toolchain) corrupts PE DLLs — python311.dll became unloadable
    # and the windowed bootloader hung on a modal error dialog.
    strip=(sys.platform != "win32"),
    upx=True,
    # GUI app: no console window on Windows (unless TACHO_CONSOLE=1).
    console=console_build,
    # Never show the modal traceback dialog: on headless CI it blocks the
    # smoke test forever; errors must surface as a nonzero exit code.
    disable_windowed_traceback=True,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=win_icon if sys.platform == "win32" and os.path.exists(win_icon) else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    # Never strip on Windows: binutils strip (present on CI runners via the
    # Git/MinGW toolchain) corrupts PE DLLs — python311.dll became unloadable
    # and the windowed bootloader hung on a modal error dialog.
    strip=(sys.platform != "win32"),
    upx=True,
    upx_exclude=[],
    name='TachoReader',
)

# Mac specific configuration
app = BUNDLE(
    coll,
    name='TachoReader.app',
    icon=mac_icon if os.path.exists(mac_icon) else None,
    bundle_identifier='com.ddd.tachoreader',
    version=__version__,
)
