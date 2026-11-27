# -*- mode: python ; coding: utf-8 -*-
"""CXPurePlayer macOS .app 构建配置。

libmpv 动态库由 CI 从 LGPL 构建包下载到 bin/，随 app 一起分发；
dylib 放到 Contents/MacOS/bin，libmpv 自带 @loader_path rpath 可解析同级依赖。
"""
import glob
import os
import re

import PySide6

# SPECPATH 由 PyInstaller 提供，指向本 spec 所在目录，避免依赖构建时的工作目录。
_SPEC_DIR = os.path.abspath(SPECPATH)
_ROOT = os.path.abspath(os.path.join(_SPEC_DIR, "..", ".."))

_version_text = open(os.path.join(_ROOT, "app", "version.py"), encoding="utf-8").read()
APP_VERSION = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', _version_text, re.M).group(1)
ARCH = os.environ.get("CXPUREPLAYER_MAC_ARCH", "arm64")

block_cipher = None

datas = []
for relative, target in [
    ("app/resources/logo.png", "app/resources"),
    ("app/resources/icon.icns", "app/resources"),
    ("THIRD_PARTY_NOTICES.md", "."),
    ("LICENSE", "."),
    ("LICENSE.GPL3", "."),
]:
    source = os.path.join(_ROOT, relative.replace("/", os.sep))
    if os.path.exists(source):
        datas.append((source, target))

for source in sorted(glob.glob(os.path.join(_ROOT, "bin", "licenses", "*"))):
    if os.path.isfile(source):
        datas.append((source, "licenses"))

runtime_readme = os.path.join(_ROOT, "bin", "README-runtime.md")
if os.path.isfile(runtime_readme):
    datas.append((runtime_readme, "licenses"))

_qt_translations = os.path.join(os.path.dirname(PySide6.__file__), "translations")
for _name in ("qtbase_zh_CN.qm", "qtbase_zh_TW.qm", "qtbase_en.qm"):
    _path = os.path.join(_qt_translations, _name)
    if os.path.exists(_path):
        datas.append((_path, "translations"))

binaries = []
for source in sorted(glob.glob(os.path.join(_ROOT, "bin", "*.dylib"))):
    # 同时保留版本化 dylib 与 libmpv.dylib 链接名，方便 find_library 和 @rpath 查找。
    binaries.append((source, "bin"))

excludes = [
    'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtQuick3D', 'PySide6.QtQuickWidgets',
    'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtWebChannel',
    'PySide6.Qt3DCore', 'PySide6.Qt3DRender', 'PySide6.Qt3DInput', 'PySide6.Qt3DLogic',
    'PySide6.QtPdf', 'PySide6.QtPdfWidgets', 'PySide6.QtCharts', 'PySide6.QtDataVisualization',
    'PySide6.QtDesigner', 'PySide6.QtHelp', 'PySide6.QtMultimedia', 'PySide6.QtNetwork',
    'PySide6.QtBluetooth', 'PySide6.QtNfc', 'PySide6.QtPositioning', 'PySide6.QtSensors',
    'PySide6.QtSerialPort', 'PySide6.QtSql', 'PySide6.QtTest', 'PySide6.QtSvg',
    'PySide6.QtUiTools', 'PySide6.QtXml',
    'tkinter', 'matplotlib', 'numpy', 'PIL', 'scipy', 'pytest', 'unittest',
]

a = Analysis(
    [os.path.join(_ROOT, 'main.py')],
    pathex=[_ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=['mpv', 'PySide6.QtOpenGLWidgets'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

icon = os.path.join(_ROOT, 'app', 'resources', 'icon.icns')
if not os.path.exists(icon):
    icon = None

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='CXPurePlayer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=ARCH,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name='CXPurePlayer',
)

app = BUNDLE(
    coll,
    name=f'CXPurePlayer-{APP_VERSION}-macos-{ARCH}.app',
    icon=icon,
    bundle_identifier='com.cxpureplayer.player',
    info_plist={
        'CFBundleName': 'CXPurePlayer',
        'CFBundleDisplayName': 'CXPurePlayer',
        'CFBundleShortVersionString': APP_VERSION.lstrip('v'),
        'CFBundleVersion': APP_VERSION.lstrip('v'),
        'LSMinimumSystemVersion': '11.0',
        'NSHighResolutionCapable': True,
        'CFBundleDocumentTypes': [{
            'CFBundleTypeName': 'Media files',
            'CFBundleTypeRole': 'Viewer',
            'CFBundleTypeExtensions': [
                'mp4', 'mkv', 'mov', 'avi', 'ts', 'flv', 'webm', 'm4v',
                'wmv', 'm2ts', 'mpg', 'mpeg', '3gp', 'aac', 'mp3', 'flac', 'wav',
            ],
        }],
    },
)
