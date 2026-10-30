# 第三方 (MIT)

存档工具 `save_tool.py` 用的两个小库, 原样取自 PyPI, 协议见各自目录下的 `LICENSE`:

- `tkinterdnd2` 0.7.0: 把文件拖进窗口 (tkdnd 的 Python 封装, 自带各平台的小型动态库; 只保留 Linux/Windows/macOS 的 Tcl 8.6 版本)。
- `sv_ttk` 2.6.1: 界面主题 (Sun Valley)。

缺了它们或平台不支持时, 工具退回成「点一下选文件」和 tkinter 自带的外观, 仍可用。`tools/saves` 整个不属于公开版导出。
