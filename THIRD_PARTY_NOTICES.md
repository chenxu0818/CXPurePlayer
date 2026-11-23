# 第三方组件与许可声明

本项目源代码采用 **LGPL-3.0-or-later** 开源（根目录 `LICENSE`，其引用的 GPLv3 全文见 `LICENSE.GPL3`）。发行依赖组合同样为 LGPL，以下组件随发行包提供或动态链接：

| 组件 | 许可 | 说明 / 来源 |
| --- | --- | --- |
| CXPurePlayer 本项目源代码 | LGPL-3.0-or-later | 本项目自有代码，见根目录 `LICENSE` |
| PySide6 | LGPLv3（Qt 6） | PyPI 官方 wheel；按 LGPLv3 使用，随包提供 Qt/PySide6 许可文本与源码获取说明 |
| libmpv (`libmpv-2.dll`) | LGPL-2.1-or-later | 使用 `zhongfly/mpv-winbuild` 的 `mpv-dev-lgpl-*` 构建（`-Dgpl=false`），内部静态链接 LGPL-3.0-or-later FFmpeg；动态链接、保持 DLL 可替换 |
| FFmpeg（内置于 libmpv） | LGPL-3.0-or-later | 随 LGPL libmpv 静态链接；本应用不单独分发 ffmpeg.exe / ffprobe.exe |
| python-mpv | 继承 libmpv 许可 | 绑定代码来自 `mpv-player/python-mpv` |
| PyInstaller | GPLv2 + 打包例外 | 允许打包专有应用；仅修改 PyInstaller 源码时才需公开修改 |

## 合规要求

1. 随发行包保留本文件、`LICENSE`（LGPLv3）与 `LICENSE.GPL3`（GPLv3 全文）及各组件许可证文本。
2. `libmpv-2.dll` 必须保持可替换（不加密、不禁止替换）。
3. `THIRD_PARTY_NOTICES.md` 应记录精确版本 / commit、构建来源链接。
4. 若后续引入新依赖（例如 QtNetwork、QtSvg 或 GPL FFmpeg），需重新审查许可组合。
5. 联网播放 / 录制不会触发额外开源义务：GPLv2/v3 无网络触发条款（AGPL 才有），本项目不引入 AGPL 组件。

> 本声明为工程与发行说明，不构成法律意见；正式商业发行前建议由法务复核。
