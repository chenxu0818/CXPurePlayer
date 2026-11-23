# -*- mode: python ; coding: utf-8 -*-
import os

import PySide6

# SPECPATH 由 PyInstaller 提供，指向本 spec 所在目录，避免依赖构建时的工作目录。
_SPEC_DIR = os.path.abspath(SPECPATH)
_ROOT = os.path.abspath(os.path.join(_SPEC_DIR, "..", ".."))

block_cipher = None

datas = []
for relative, target in [
    ("bin/libmpv-2.dll", "bin"),
    ("app/resources/logo.png", "app/resources"),
    ("app/resources/icon.ico", "app/resources"),
    ("THIRD_PARTY_NOTICES.md", "."),
    ("LICENSE", "."),
    ("LICENSE.GPL3", "."),
]:
    source = os.path.join(_ROOT, relative.replace("/", os.sep))
    if os.path.exists(source):
        datas.append((source, target))

# Qt 标准对话框（打开/保存/消息框）按钮的中文/英文翻译
_qt_translations = os.path.join(os.path.dirname(PySide6.__file__), "translations")
for _name in ("qtbase_zh_CN.qm", "qtbase_zh_TW.qm", "qtbase_en.qm"):
    _path = os.path.join(_qt_translations, _name)
    if os.path.exists(_path):
        datas.append((_path, "translations"))

excludes = [
    'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtQuick3D', 'PySide6.QtQuickWidgets',
    'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtWebChannel',
    'PySide6.Qt3DCore', 'PySide6.Qt3DRender', 'PySide6.Qt3DInput', 'PySide6.Qt3DLogic',
    'PySide6.QtPdf', 'PySide6.QtPdfWidgets', 'PySide6.QtCharts', 'PySide6.QtDataVisualization',
    'PySide6.QtDesigner', 'PySide6.QtHelp', 'PySide6.QtMultimedia', 'PySide6.QtNetwork',
    'PySide6.QtBluetooth', 'PySide6.QtNfc', 'PySide6.QtPositioning', 'PySide6.QtSensors',
    'PySide6.QtSerialPort', 'PySide6.QtSql', 'PySide6.QtTest', 'PySide6.QtSvg',
    'PySide6.QtOpenGL', 'PySide6.QtOpenGLWidgets', 'PySide6.QtUiTools', 'PySide6.QtXml',
    'tkinter', 'matplotlib', 'numpy', 'PIL', 'scipy', 'pytest', 'unittest',
]

a = Analysis(
    [os.path.join(_ROOT, 'main.py')],
    pathex=[_ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=['mpv'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# --- EXE 瘦身：裁剪 PySide6 hook 全量收集但本项目未使用的二进制 ---
# 项目只使用 QtCore / QtGui / QtWidgets。已用 PE 导入表确认：Qt6Core/Qt6Gui/
# Qt6Widgets 及三个 .pyd 仅互相依赖，下列 DLL 均为 hook 顺带收集，从未加载。
# 保留：qwindows.dll（唯一运行时平台插件）、qico.dll（ICO 资源）、
#       qjpeg.dll（截图/外部图片）、qmodernwindowsstyle.dll（原生样式）。
# 应急回退：设置环境变量 CXPUREPLAYER_KEEP_QT_ALL=1 可跳过裁剪。
_TRIM_QT_BINARIES = {
    # 大型未用 Qt 模块
    "opengl32sw.dll",          # 软件 OpenGL 回退（无 OpenGL 控件）
    "qt6quick.dll", "qt6qml.dll", "qt6qmlmodels.dll",
    "qt6qmlmeta.dll", "qt6qmlworkerscript.dll",
    "qt6pdf.dll", "qt6svg.dll", "qt6network.dll", "qt6opengl.dll",
    "qt6virtualkeyboard.dll",
    # 未用 Qt 插件（图标自绘，无需 SVG；仅保留 ICO/JPEG）
    "qtuiotouchplugin.dll", "qsvgicon.dll", "qgif.dll", "qicns.dll",
    "qpdf.dll", "qsvg.dll", "qtga.dll", "qtiff.dll", "qwbmp.dll",
    "qwebp.dll", "qtvirtualkeyboardplugin.dll",
    # 平台插件：仅保留 qwindows.dll
    "qdirect2d.dll", "qminimal.dll", "qoffscreen.dll",
}
if os.environ.get("CXPUREPLAYER_KEEP_QT_ALL") != "1":
    _trimmed, _kept_binaries = [], []
    for _item in a.binaries:
        if os.path.basename(_item[0]).lower() in _TRIM_QT_BINARIES:
            _trimmed.append(os.path.basename(_item[0]))
        else:
            _kept_binaries.append(_item)
    a.binaries = _kept_binaries
    print("[build] 已裁剪 %d 项未使用 Qt 二进制: %s"
          % (len(_trimmed), ", ".join(sorted(set(_trimmed)))))
else:
    print("[build] 环境变量 CXPUREPLAYER_KEEP_QT_ALL=1，跳过 Qt 二进制裁剪")

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],
    name='CXPurePlayer-v1.0.0-win-x64',
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
    version=os.path.join(_SPEC_DIR, 'version_info.txt'),
    icon=os.path.join(_ROOT, 'app', 'resources', 'icon.ico')
         if os.path.exists(os.path.join(_ROOT, 'app', 'resources', 'icon.ico')) else None,
)
