# PyInstaller spec for Fizzy. Build with packaging\build.ps1, or:
#   pyinstaller packaging/fizzy.spec --distpath dist --workpath build/pyinstaller

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent
ICON = ROOT / "build" / "fizzy.ico"

datas = collect_data_files("fizzy", includes=["**/*.md"])
binaries = []
hiddenimports = collect_submodules("fizzy") + collect_submodules("keyring.backends")

# Packages that ship models, DLLs or config files next to their code.
for pkg in ("faster_whisper", "ctranslate2", "rapidocr_onnxruntime", "uiautomation"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "IPython", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Fizzy",
    console=False,
    icon=str(ICON) if ICON.exists() else None,
    upx=False,
)

coll = COLLECT(exe, a.binaries, a.datas, name="Fizzy", upx=False)
