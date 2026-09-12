# PyInstaller spec per Soldoni — eseguibile onedir con finestra nativa.
from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

datas = []
binaries = []
hiddenimports = []

for pkg in ("streamlit", "streamlit_option_menu", "plotly"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# dashboard.py deve esistere su disco: bootstrap.run riceve un path di file.
datas += [("soldoni/app/dashboard.py", ".")]
datas += copy_metadata("streamlit")

hiddenimports += collect_submodules("soldoni")
hiddenimports += ["pyarrow"]

a = Analysis(
    ["soldoni/app/desktop.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "torch", "torchvision", "torchaudio",
        "tensorflow", "tensorboard",
        "nvidia", "triton",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Soldoni",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    icon="assets/soldoni.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Soldoni",
)
