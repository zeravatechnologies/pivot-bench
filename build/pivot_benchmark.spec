# PyInstaller spec for the Pivot Benchmark application (Windows and Linux).
#   pyinstaller --noconfirm build/pivot_benchmark.spec
# Produces dist/PivotBenchmark/ with the executable and everything it needs:
# its own Python, the engine, the web app, the frozen ladders, personas,
# lexicons and the default config. llama.cpp is NOT included (the user installs it).
import os
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = os.path.abspath(os.path.join(os.path.dirname(SPEC), ".."))
sys.path.insert(0, ROOT)
from mbench.version import VERSION  # noqa: E402

datas = [
    (os.path.join(ROOT, "ladders", "*.yaml"), "ladders"),
    (os.path.join(ROOT, "personas"), "personas"),
    (os.path.join(ROOT, "lexicons"), "lexicons"),
    (os.path.join(ROOT, "web", "static"), os.path.join("web", "static")),
    (os.path.join(ROOT, "mbench", "models.yaml"), "mbench"),
    (os.path.join(ROOT, "config.yaml"), "."),
    (os.path.join(ROOT, "canary.yaml"), "."),
    (os.path.join(ROOT, "README.md"), "."),
]
hidden = (collect_submodules("uvicorn") + collect_submodules("fastapi") + collect_submodules("starlette")
          + ["yaml", "anyio._backends._asyncio", "mbench", "mbench.webapp", "mbench.manager",
             "mbench.orchestrator", "mbench.paths", "mbench.version", "mbench.llama_check"]
          + collect_submodules("mbench"))

a = Analysis(
    [os.path.join(ROOT, "pivot_app.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    excludes=["PyQt5", "PyQt6", "PyQt5.sip", "PyQt6.sip", "tkinter", "tests", "gui", "pytest", "numpy", "pandas", "matplotlib", "scipy", "IPython", "tkinter",
              "PySide6.QtQml", "PySide6.Qt3DCore", "PySide6.QtCharts", "PySide6.QtMultimedia",
              "PySide6.QtQuick", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtXml", "PySide6.QtBluetooth",
              "PySide6.QtNfc", "PySide6.QtSensors", "PySide6.QtSerialPort", "PySide6.QtPdf", "PySide6.QtDesigner"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="PivotBenchmark",
    debug=False, strip=False, upx=False,
    console=False,                  # a GUI app: no black console window behind it
    icon=os.path.join(ROOT, "build", "pivot.ico") if os.path.exists(os.path.join(ROOT, "build", "pivot.ico")) else None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="PivotBenchmark")
