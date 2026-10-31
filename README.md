# SwordmanHD-SaveTool

[SwordmanHD](https://github.com/zmnqaz/SwordmanHD) (《天地劫：神魔至尊传》高清复刻) 的存档工具: 把原版营地存档 (`GD00.GSF` ~ `GD04.GSF`) 和复刻版存档 (`save1.json` ~ `save5.json`) 互相转换, 也能直接修改复刻版存档的金钱、行囊和人物。把存档拖进窗口就转换, 转好的存档一键放进游戏。

## 下载

到 [Releases](https://github.com/zmnqaz/SwordmanHD-SaveTool/releases) 下载自己系统的压缩包, 解压后双击 `SaveTool` (Windows 是 `SaveTool.exe`), 不用装 Python。macOS 第一次打开要右键 → 打开。想要最新的: 本仓库 Actions 页面里每次构建的 Artifacts。

## 使用 (从源码)

需要 Python 3.10 以上 (Windows / macOS 的官方安装包自带界面库; Linux 上 `sudo apt install python3-tk`)。

- **Windows**: 把存档文件拖到 `SaveTool.bat` 上, 或双击它打开窗口再拖。
- **Linux / macOS**: `python3 savetool/save_tool.py`。

三个页面:

| 页面 | 拖进来 | 得到 |
|---|---|---|
| 原版 → 复刻版 | 原版的 `GD00.GSF` ~ `GD04.GSF` | 复刻版的 `save1.json` ~ `save5.json` |
| 复刻版 → 原版 | 复刻版的 `save1.json` ~ `save5.json` | 原版的 `GD00.GSF` ~ `GD04.GSF` |
| 修改存档 | 复刻版的 `save1.json` ~ `save5.json` | 改好的复刻版存档 (见下) |

转好的存档放在**源文件旁边的「转换后的存档」文件夹**里 (窗口里显示完整路径), 拖进来的文件不会被改动。想直接用: 选存档位, 点「放进游戏」。复刻版存档放进游戏自己的存档目录 (自动), 原版存档放进原版游戏文件夹 (第一次选一下, 以后记住)。那个存档位已有存档时会先问你, 替换前旧存档自动备份。

存档文件在哪:

| | 位置 |
|---|---|
| 原版 | 原版游戏文件夹里的 `GD00.GSF` ~ `GD04.GSF` (营地的 5 个存档位) |
| 复刻版 Windows | `%APPDATA%\SwordmanHD\` (即 `C:\Users\你的用户名\AppData\Roaming\SwordmanHD\`) |
| 复刻版 Linux | `~/.local/share/SwordmanHD/` |
| 复刻版 macOS | `~/Library/Application Support/SwordmanHD/` |
| 复刻版 Android | 游戏的真存档在应用私有目录 `/data/data/com.tdj.swordmanhd/files/saves` (没 root 进不去); 游戏同时会同步一份到 `/sdcard/Android/data/com.tdj.swordmanhd/files/saves/`, 用电脑拷出来改, 改完拷回去 |

## 修改存档

「修改存档」页直接改**复刻版**存档: 页顶会提示这台电脑上的存档位置, 那里有存档的话点「存档 N」直接打开 (也可以点「打开存档…」或把 `saveN.json` 拖进来), 改完点「保存」, 旧存档会先自动备份成 `saveN.json.bak-日期时间`。能改:

| 能改 | 范围 |
|---|---|
| 金钱 | 0 ~ 2147483647 |
| 公共行囊 | 加、删物品, 改数量, 最多 512 件 |
| 等级 / 经验 | 1 ~ 99 / 0 ~ 32767 |
| HP 上限 / MP 上限 | 1 ~ 32767 / 0 ~ 32767 |
| 力 智 敏 体 运 | 各 0 ~ 500 |
| 五魂、五魂点 | 0 ~ 32767 |
| 装备、技能、随身物品 | 装备类型要和栏位一致且这个人能装; 技能、随身物品各最多 10 格 |

超出范围会被拒绝并提示范围, 不会悄悄截断; 没改的内容 (包括剧情变量) 原样保留。不改剧情变量和关卡进度, 改错容易卡关。改完的存档仍可用「复刻版 → 原版」页转回原版格式 (上面的范围就是按原版存档能存下的值取的)。

**按名字搜索物品、技能**不需要资源包: 程序内置了一份精简名字表 (只有物品、技能、人物的编号和名字, 物品的类型和谁能装, 没有说明文字和数值)。装备栏只列出这个人能装的、类型对得上的物品。

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
