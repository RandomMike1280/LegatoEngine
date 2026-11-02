# PyInstaller spec for LegatoEngine.app. Build it with packaging/build_app.sh.
import os

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, copy_metadata

import legatoengine

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

datas = collect_data_files("legatoengine")
datas += collect_data_files("transkun", includes=["pretrained/*"])  # the transcription model's weights
datas += collect_data_files("swift_f0", includes=["model.onnx"])  # the melody and bass pitch model
datas += copy_metadata("tqdm") + copy_metadata("swift-f0")  # swift_f0 reads its version when imported
# MLX (the separator on Apple Silicon) looks for its GPU kernels, mlx.metallib, next to libmlx.dylib
datas += collect_data_files("mlx", includes=["lib/mlx.metallib"])
binaries = collect_dynamic_libs("mlx")

a = Analysis(
    [os.path.join(SPECPATH, "legatoengine_app.py")],
    pathex=[os.path.join(ROOT, "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=["legatoengine.gui.main_window", "mlx._reprlib_fix", "mlx.__array_api_info"],  # imported by mlx.core's C code
    module_collection_mode={"transkun": "pyz+py"},  # TorchScript compiles transkun's Viterbi from its .py source
    # MuScriptor's web app and command line, and the beat tracker it only uses for sheet music
    excludes=["tkinter", "IPython", "pytest", "torch.utils.tensorboard", "beat_this", "fastapi", "starlette", "uvicorn", "typer"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LegatoEngine",
    console=False,
    argv_emulation=False,  # Qt turns Finder "open" requests into QFileOpenEvents
    target_arch="arm64",
)
coll = COLLECT(exe, a.binaries, a.datas, name="LegatoEngine")
app = BUNDLE(
    coll,
    name="LegatoEngine.app",
    bundle_identifier="local.legatoengine.LegatoEngine",
    version=legatoengine.__version__,
    info_plist={
        "CFBundleDisplayName": "LegatoEngine",
        "LSMinimumSystemVersion": "13.0",
        "LSApplicationCategoryType": "public.app-category.music",
        "NSHighResolutionCapable": True,
        "CFBundleDocumentTypes": [
            {
                "CFBundleTypeName": "LegatoEngine script",
                "CFBundleTypeExtensions": ["apno"],
                "CFBundleTypeRole": "Viewer",
                "LSHandlerRank": "Owner",
            },
            {
                "CFBundleTypeName": "Song",
                "LSItemContentTypes": ["public.audio", "public.midi-audio"],
                "CFBundleTypeRole": "Viewer",
                "LSHandlerRank": "Alternate",
            },
        ],
    },
)
