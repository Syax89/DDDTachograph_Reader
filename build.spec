# -*- mode: python ; coding: utf-8 -*-
import os
import sys
import customtkinter
from PyInstaller.utils.hooks import collect_data_files

# Percorso della directory base
base_path = os.path.abspath(".")

# Raccogli i file di dati di customtkinter
# PyInstaller spesso ha problemi a trovare i file .json e .txt di customtkinter
ctk_path = os.path.dirname(customtkinter.__file__)
ctk_data = [(ctk_path, "customtkinter")]

# Aggiungi i certificati
certs_path = os.path.join(base_path, "certs")
added_files = []
if os.path.exists(certs_path):
    added_files.append((certs_path, "certs"))
    
added_files.extend(ctk_data)

# Configurazione PyInstaller
block_cipher = None

a = Analysis(
    ['gui.py'],
    pathex=[base_path],
    binaries=[],
    datas=added_files,
    hiddenimports=['cryptography', 'requests'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    strip=False,
    upx=True,
    console=False,
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
    strip=False,
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
