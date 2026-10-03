# -*- mode: python ; coding: utf-8 -*-
import os

from PyInstaller.utils.hooks import collect_data_files


ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
datas = [
    (os.path.join(ROOT, "assets", "hotspot-logger.png"), "assets"),
    (os.path.join(ROOT, "build", "branding", "hotspot-logger-icon.png"), "assets"),
] + collect_data_files("tzdata")

a = Analysis(
    [os.path.join(SPECPATH, "launcher.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=["app", "tzdata", "pystray._win32"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="HotspotLogger",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(ROOT, "build", "branding", "hotspot-logger.ico"),
    version=os.path.join(SPECPATH, "version_info.txt"),
    uac_admin=False,
    uac_uiaccess=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="HotspotLogger",
)
