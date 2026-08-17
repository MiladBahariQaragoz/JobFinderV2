# PyInstaller build recipe. Everything it needs is a list in the package, where
# tests can read it: see jobfinder/packaging.py and tests/unit/test_packaging.py.
from jobfinder.packaging import APP_NAME, ENTRY_SCRIPT, HIDDEN_IMPORTS, spec_datas

analysis = Analysis(  # noqa: F821  (PyInstaller injects this at exec time)
    [ENTRY_SCRIPT],
    pathex=["src"],
    datas=spec_datas(),
    hiddenimports=list(HIDDEN_IMPORTS),
    noarchive=False,
)

pyz = PYZ(analysis.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    name=APP_NAME,
    console=True,  # the little window is the status line she reads
    upx=False,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
)
