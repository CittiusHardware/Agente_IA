# PyInstaller onedir build for the local Streamlit application.
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules

project_root = Path(SPECPATH).resolve()
sys.path.insert(0, str(project_root / "src"))
collected_datas = [(str(project_root / "app.py"), ".")]
collected_binaries = []
collected_hiddenimports = []
for package in ("streamlit", "pdfplumber", "pdfminer", "pypdfium2"):
    package_datas, package_binaries, package_hiddenimports = collect_all(package)
    collected_datas += package_datas
    collected_binaries += package_binaries
    collected_hiddenimports += package_hiddenimports
collected_hiddenimports += collect_submodules("agente_pdf")

a = Analysis(
    [str(project_root / "app_launcher.py")],
    pathex=[str(project_root / "src")],
    binaries=collected_binaries,
    datas=collected_datas,
    hiddenimports=collected_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ComparadorPDF",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ComparadorPDF",
)
