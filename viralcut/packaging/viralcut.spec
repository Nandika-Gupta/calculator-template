# PyInstaller spec for the Windows desktop app. Build from the repo root:
#   pyinstaller --noconfirm --clean viralcut/packaging/viralcut.spec
# Expects build_assets/ffmpeg (ffmpeg.exe, ffprobe.exe + DLLs) and build_assets/fonts (Anton-Regular.ttf).
import os

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))

datas = [
    (os.path.join(ROOT, "viralcut", "web"), os.path.join("viralcut", "web")),
    (os.path.join(ROOT, "build_assets", "ffmpeg"), "ffmpeg"),
    (os.path.join(ROOT, "build_assets", "fonts"), "fonts"),
]
binaries = []
hiddenimports = ["viralcut.app"] + collect_submodules("uvicorn") + collect_submodules("yt_dlp")
for package in ("faster_whisper", "ctranslate2", "onnxruntime", "av", "tokenizers"):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden
datas += collect_data_files("cv2")  # Haar cascades for face tracking

a = Analysis(
    [os.path.join(SPECPATH, "launcher.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "torch", "pytest", "pandas", "scipy", "IPython"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ViralCut",
    icon=os.path.join(SPECPATH, "icon.ico"),
    console=True,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="ViralCut", upx=False)
