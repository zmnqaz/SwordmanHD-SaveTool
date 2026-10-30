#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""打包成不用装 Python 的程序: python3 build.py  ->  dist/SwordmanHD-SaveTool-<系统>.zip

需要: pip install pyinstaller (打包机上的 Python 要带 tkinter)。
Windows 出单个 SaveTool.exe, macOS 出 SaveTool.app, Linux 出单个 SaveTool; 都带着界面库和拖放库 (savetool/_vendor)。
GitHub 上的自动打包见 .github/workflows/build.yml。
"""
import os
import platform
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(HERE, "dist")
NAME = "SaveTool"
SYSTEMS = {"Windows": "windows", "Darwin": "macos", "Linux": "linux"}


def pyinstaller_args(system, work):
    """PyInstaller 的参数。_vendor 整个当数据带上: 程序启动时把它加进 sys.path, 和直接跑脚本时一样。"""
    sep = os.pathsep
    args = ["--noconfirm", "--clean", "--windowed", "--name", NAME,
            "--distpath", work, "--workpath", os.path.join(work, "build"), "--specpath", os.path.join(work, "build"),
            "--add-data", os.path.join(HERE, "savetool", "_vendor") + sep + "_vendor",
            "--paths", os.path.join(HERE, "savetool")]
    args += ["--onedir"] if system == "Darwin" else ["--onefile"]
    return args + [os.path.join(HERE, "savetool", "save_tool.py")]


def main():
    system = platform.system()
    if system not in SYSTEMS:
        sys.exit("不认识的系统: %s" % system)
    tag = "%s-%s" % (SYSTEMS[system], platform.machine().lower().replace("amd64", "x64").replace("x86_64", "x64"))
    work = os.path.join(DIST, "work")
    shutil.rmtree(work, ignore_errors=True)
    subprocess.run([sys.executable, "-m", "PyInstaller"] + pyinstaller_args(system, work), check=True)

    stage = os.path.join(DIST, "SwordmanHD-SaveTool-" + tag)
    shutil.rmtree(stage, ignore_errors=True)
    os.makedirs(stage)
    if system == "Darwin":
        shutil.copytree(os.path.join(work, NAME + ".app"), os.path.join(stage, NAME + ".app"), symlinks=True)
    else:
        exe = NAME + (".exe" if system == "Windows" else "")
        shutil.copy2(os.path.join(work, exe), os.path.join(stage, exe))
    for f in ("README.md", "LICENSE", "NOTICE.md"):
        shutil.copy2(os.path.join(HERE, f), stage)
    zip_path = stage + ".zip"
    if system == "Darwin":   # .app 里有符号链接和可执行位, 只有 ditto 打得对
        subprocess.run(["ditto", "-c", "-k", "--keepParent", stage, zip_path], check=True)
    else:
        shutil.make_archive(stage, "zip", DIST, os.path.basename(stage))
    shutil.rmtree(work, ignore_errors=True)
    print(zip_path)


if __name__ == "__main__":
    main()
