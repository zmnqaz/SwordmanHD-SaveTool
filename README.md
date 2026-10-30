# SwordmanHD-SaveTool

[SwordmanHD](https://github.com/zmnqaz/SwordmanHD) (《天地劫：神魔至尊传》高清复刻) 的存档转换工具: 原版营地存档 (`GD00.GSF` ~ `GD04.GSF`) 和复刻版存档 (`save1.json` ~ `save5.json`) 互相转换。把存档拖进窗口就转换, 转好的存档一键放进游戏。

## 下载

到 [Releases](https://github.com/zmnqaz/SwordmanHD-SaveTool/releases) 下载自己系统的压缩包, 解压后双击 `SaveTool` (Windows 是 `SaveTool.exe`), 不用装 Python。macOS 第一次打开要右键 → 打开。想要最新的: 本仓库 Actions 页面里每次构建的 Artifacts。

## 使用 (从源码)

需要 Python 3.10 以上 (Windows / macOS 的官方安装包自带界面库; Linux 上 `sudo apt install python3-tk`)。

- **Windows**: 把存档文件拖到 `SaveTool.bat` 上, 或双击它打开窗口再拖。
- **Linux / macOS**: `python3 savetool/save_tool.py`。

两个页面:

| 页面 | 拖进来 | 得到 |
|---|---|---|
| 原版 → 复刻版 | 原版的 `GD00.GSF` ~ `GD04.GSF` | 复刻版的 `save1.json` ~ `save5.json` |
| 复刻版 → 原版 | 复刻版的 `save1.json` ~ `save5.json` | 原版的 `GD00.GSF` ~ `GD04.GSF` |

转好的存档放在**源文件旁边的「转换后的存档」文件夹**里 (窗口里显示完整路径), 拖进来的文件不会被改动。想直接用: 选存档位, 点「放进游戏」。复刻版存档放进游戏自己的存档目录 (自动), 原版存档放进原版游戏文件夹 (第一次选一下, 以后记住)。那个存档位已有存档时会先问你, 替换前旧存档自动备份。

存档文件在哪:

| | 位置 |
|---|---|
| 原版 | 原版游戏文件夹里的 `GD00.GSF` ~ `GD04.GSF` (营地的 5 个存档位) |
| 复刻版 Windows | `%APPDATA%\SwordmanHD\` |
| 复刻版 Linux | `~/.local/share/SwordmanHD/` |
| 复刻版 macOS | `~/Library/Application Support/SwordmanHD/` |

## 命令行 (不想开窗口时)

```
python3 savetool/import_gsf.py <原版游戏文件夹> [--dry-run] [--force]     # 原版 → 复刻版
python3 savetool/export_gsf.py <复刻版存档文件夹> --out <原版游戏文件夹> [--dry-run] [--force]   # 复刻版 → 原版
```

缺省不覆盖已有存档, 加 `--force` 才覆盖 (覆盖前旧文件先备份); `--dry-run` 只看不写。

## 注意

- 只转**营地存档**。原版的战阵存档 `GAMEDATA.GCF` 要用游戏引擎转换, 这里不带, 见 SwordmanHD 仓库的 `tools/saves/import_gcf.py`。
- **复刻版 → 原版还没有用原版程序实际读过**: 格式经 15 份原版存档「导入再导出」逐字节核对过, 但导出前请先备份你的原版存档。
- 复刻版存档里的剧情变量、行囊等超出原版容量的部分会被丢弃 (会在输出里提示)。

## 打包

`pip install pyinstaller && python3 build.py` -> `dist/SwordmanHD-SaveTool-<系统>.zip`。GitHub 上推送即自动打包 (`.github/workflows/build.yml`), 打 `v*` 标签会发布到 Releases。

## 测试

`python3 -m unittest discover tests`

## 许可

GPL-3.0-only, 见 [LICENSE](LICENSE); 随仓库带的第三方库见 [NOTICE.md](NOTICE.md)。
