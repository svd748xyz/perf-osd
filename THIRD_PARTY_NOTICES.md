# 第三方组件

## PresentMon（`tools/PresentMon.exe`）

- 项目：https://github.com/GameTechDev/PresentMon
- 版本：2.6.0（x64 独立可执行文件）
- 版权：Copyright (c) 2017-2024 Intel Corporation
- 许可证：MIT

本项目只是以子进程方式调用它（`--output_stdout` 读 CSV），没有修改、没有链接。
它通过 ETW 采集 `DXGI / D3D Present` 事件算出帧时长，**不会注入任何进程**。

> 保留原样分发；如需最新版，去上面那个仓库下载替换 `tools/PresentMon.exe` 即可。

---

## 字体

运行时从系统读取，不随仓库分发：

- Consolas（等宽数字）/ Microsoft YaHei（中文字形）
- 找不到时依次退到 Arial → `ImageFont.load_default()`

---

## 其他

纯手写，没有其他第三方运行时依赖；唯一的 pip 包是 `pillow`（MIT-CMU），只用来画那层透明面板。
