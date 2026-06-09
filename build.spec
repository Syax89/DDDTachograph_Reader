# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from PyInstaller.utils.hooks import collect_data_files

# Percorso della directory base
base_path = os.path.abspath(".")

# La GUI (gui_tree.py) usa solo tkinter/ttk puro — nessuna dipendenza esterna.
ctk_data = []

# Raccogli solo i file essenziali di reportlab (font Type1 e afm — esclude test/samples)
try:
    import reportlab
    rl_path = os.path.dirname(reportlab.__file__)
    for subdir in ['fonts', 'lib', 'platypus', 'graphics', 'pdfgen', 'pdfbase']:
        full = os.path.join(rl_path, subdir)
        if os.path.exists(full):
            ctk_data.append((full, os.path.join("reportlab", subdir)))
except ImportError:
    pass

# Aggiungi i certificati
certs_path = os.path.join(base_path, "certs")
added_files = []
if os.path.exists(certs_path):
    added_files.append((certs_path, "certs"))

# Aggiungi i package core/ e src/ esplicitamente
core_path = os.path.join(base_path, "core")
if os.path.exists(core_path):
    added_files.append((core_path, "core"))

src_path = os.path.join(base_path, "src")
if os.path.exists(src_path):
    added_files.append((src_path, "src"))
    
added_files.extend(ctk_data)

# Configurazione PyInstaller
block_cipher = None

a = Analysis(
    ['gui_tree.py'],
    pathex=[base_path, os.path.join(base_path, 'core'), os.path.join(base_path, 'src')],
    binaries=[],
    datas=added_files,
    hiddenimports=[
        'tkinter',
        'cryptography',
        'requests',
        'reportlab',
        'reportlab.lib',
        'reportlab.lib.colors',
        'reportlab.lib.pagesizes',
        'reportlab.lib.units',
        'reportlab.lib.styles',
        'reportlab.lib.enums',
        'reportlab.platypus',
        'reportlab.platypus.tables',
        'reportlab.graphics.shapes',
        'reportlab.graphics',
        'pandas',
        'openpyxl',
        'export_manager',
        'signature_validator',
        'core',
        'core.tag_navigator',
        'core.decoders',
        'core.models',
        'core.g2_decoders',
        'core.decoder_registry',
        'core.deterministic_parser',
        'core.record_array',
        'core.logger',
        'core.tag_definitions',
        'core.vu_record_dispatcher',
        'core.vu_signature_verifier',
        'src',
        'src.domain',
        'src.domain.models',
        'src.domain.models.entities',
        'src.domain.models.value_objects',
        'src.domain.repositories',
        'src.domain.repositories.tachograph_repository',
        'src.infrastructure',
        'src.infrastructure.repositories',
        'src.infrastructure.repositories.file_tacho_repository',
        'src.infrastructure.parsers',
        'src.infrastructure.parsers.tag_definitions',
        'src.infrastructure.mappers',
        'src.infrastructure.mappers.tacho_mapper',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Solo librerie di terze parti pesanti che l'app NON usa.
        # NB: non escludere moduli stdlib (email, html, urllib3, http, ...):
        # cryptography e requests li importano e la loro assenza fa crashare
        # l'eseguibile all'avvio.
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
    strip=True,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon='icon.ico', # Decommenta se aggiungi un'icona
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=True,
    upx=True,
    upx_exclude=[],
    name='TachoReader',
)

# Mac specific configuration
app = BUNDLE(
    coll,
    name='TachoReader.app',
    icon=None, # Decommenta se aggiungi un'icona .icns
    bundle_identifier='com.ddd.tachoreader',
)
