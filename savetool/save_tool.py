#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""存档转换工具 (界面): 两个页面, 「原版 → 复刻版」和「复刻版 → 原版」; 把存档拖进窗口就转换, 转好的可以一键放进游戏的存档位。

用法:
    python3 tools/saves/save_tool.py [存档文件 ...]     (也可以直接把存档文件拖到这个脚本上)

需要 Python 3.10+ 和 tkinter (Windows/macOS 自带; Debian/Ubuntu: sudo apt install python3-tk)。
拖拽和主题用随仓库带的 tkinterdnd2、sv_ttk (_vendor/); 加载不了时退回成「点一下选文件」和自带外观。
没有 tkinter 或没有桌面时, 转换用命令行: import_gsf.py (原版 -> 复刻) / export_gsf.py (复刻 -> 原版)。
说明见 docs/存档互通.md。逻辑在 save_ops.py, 这里只有界面。
"""
import os
import subprocess
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.append(os.path.join(HERE, "_vendor"))   # 装了系统版的就用系统版, 没装用随仓库带的
import save_ops as O  # noqa: E402
from save_ops import GsfError, SlotTaken  # noqa: E402

C = {"accent": "#005FB8", "line": "#C8CCD2", "tint": "#E5F0FB", "muted": "#6B6B6B", "ok": "#1E8E4E", "bad": "#C42B1C", "warn": "#9D5D00", "text": "#1B1B1B"}
FONT_FAMILIES = ("Microsoft YaHei UI", "PingFang SC", "Noto Sans CJK SC", "Noto Sans SC", "Source Han Sans SC", "WenQuanYi Micro Hei")

# 每一页: 方向, 页签名, 拖放区大字, 小字, 文件类型
PAGES = [
    (O.TO_REPLICA, "原版 → 复刻版", "把原版存档拖到这里", "GD00.GSF ~ GD04.GSF" + ("  /  战阵存档 GAMEDATA.GCF" if O.C else ""), [("原版存档", "*.GSF *.gsf" + (" *.GCF *.gcf" if O.C else ""))]),
    (O.TO_ORIGINAL, "复刻版 → 原版", "把复刻版存档拖到这里", "save1.json ~ save5.json", [("复刻版存档", "*.json")]),
]


def import_tk():
    """tkinter 的几个模块; 没装时给出安装提示后退出 (命令行工具仍可用)。"""
    try:
        import tkinter as tk
        from tkinter import filedialog, font, messagebox, ttk
    except ImportError:
        print("没有找到 tkinter, 界面不能用。\n"
              "  Debian/Ubuntu: sudo apt install python3-tk\n  Fedora: sudo dnf install python3-tkinter\n"
              "  Windows/macOS: 用 python.org 的安装包 (自带)\n"
              "不装的话, 转换请用命令行: tools/saves/import_gsf.py (原版 -> 复刻) 和 tools/saves/export_gsf.py (复刻 -> 原版)", file=sys.stderr)
        sys.exit(1)
    return tk, ttk, filedialog, font, messagebox


def load_dnd(root):
    """给窗口装上拖拽支持: 成功返回 DND_FILES, 这台电脑不支持返回 None。"""
    try:
        import tkinterdnd2
        tkinterdnd2.TkinterDnD._require(root)
        return tkinterdnd2.DND_FILES
    except Exception:   # 没有这个平台的库/加载失败: 不影响点选
        return None


def load_theme(root):
    try:
        import sv_ttk
        sv_ttk.set_theme("light", root)
    except Exception:   # 主题加载失败: 用 tkinter 自带外观
        pass


def open_folder(path):
    """在文件管理器里打开存档所在的文件夹 (打不开就算了)。"""
    folder = os.path.dirname(path)
    try:
        if sys.platform.startswith("win"):
            os.startfile(folder)   # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", folder])
        else:
            subprocess.Popen(["xdg-open", folder])
    except OSError:
        pass


class Page:
    """一个页面 = 一个拖放区 + 下面的结果卡片; 只收一种存档。"""

    def __init__(self, app, nb, spec):
        ttk = app.ttk
        self.app, (self.direction, title, big, small, self.types) = app, spec
        self.big, self.small = big, small
        self.frame = ttk.Frame(nb, padding=20)
        nb.add(self.frame, text=title)
        self.zone = app.tk.Canvas(self.frame, width=520, height=140, highlightthickness=0, cursor="hand2",
                                  bg=ttk.Style().lookup("TFrame", "background") or "#FAFAFA")
        self.zone.pack(fill="x")
        self.draw(False)
        self.zone.bind("<Button-1>", lambda e: self.pick())
        self.zone.bind("<Enter>", lambda e: self.draw(True))
        self.zone.bind("<Leave>", lambda e: self.draw(False))
        self.results = ttk.Frame(self.frame)
        self.results.pack(fill="x", pady=(16, 0))
        if app.dnd:
            for w in (self.frame, self.zone, self.results):
                w.drop_target_register(app.dnd)
                w.dnd_bind("<<Drop>>", self.on_drop)
                w.dnd_bind("<<DropEnter>>", lambda e: self.draw(True))
                w.dnd_bind("<<DropLeave>>", lambda e: self.draw(False))

    def draw(self, hot):
        z, f = self.zone, self.app.fam
        z.delete("all")
        w, h, r, m = int(z["width"]), int(z["height"]), 14, 3
        pts = [m + r, m, w - m - r, m, w - m, m, w - m, m + r, w - m, h - m - r, w - m, h - m, w - m - r, h - m,
               m + r, h - m, m, h - m, m, h - m - r, m, m + r, m, m]
        z.create_polygon(pts, smooth=True, fill=C["tint"] if hot else "", outline=C["accent"] if hot else C["line"], width=2, dash=(6, 4))
        z.create_text(w // 2, h // 2 - 12, text=self.big if self.app.dnd else "点这里选择存档", font=(f, 16, "bold"), fill=C["text"])
        z.create_text(w // 2, h // 2 + 22, text=self.small, font=(f, 11), fill=C["muted"])

    def pick(self):
        paths = self.app.fd.askopenfilenames(title="选择存档", filetypes=self.types + [("所有文件", "*")])
        if paths:
            self.handle(list(paths))

    def on_drop(self, event):
        self.draw(False)
        self.handle(list(self.app.root.tk.splitlist(event.data)))

    def handle(self, paths):
        for child in self.results.winfo_children():
            child.destroy()
        for p in paths:
            if p.lower().endswith(".gcf"):   # 战阵存档要启动游戏引擎转, 要几秒到几十秒: 放到后台, 窗口不卡
                self.convert_in_background(p)
            else:
                self.show(self.try_convert(p))

    def try_convert(self, path):
        try:
            return O.convert_file(path, expect=self.direction)
        except (GsfError, OSError) as e:
            return {"error": str(e) if isinstance(e, GsfError) else (e.strerror or str(e)), "src_name": os.path.basename(path)}

    def show(self, res, before=None):
        if "error" in res:
            self.bad_card(res["src_name"], res["error"], before)
        else:
            self.ok_card(res, before)

    def convert_in_background(self, path):
        holder = self.card()
        self.label(holder, "⏳  正在转换 %s ... (要启动游戏引擎, 请稍等)" % os.path.basename(path), "muted").pack(anchor="w")
        box = {}
        threading.Thread(target=lambda: box.update(res=self.try_convert(path)), daemon=True).start()

        def poll():
            if "res" not in box:
                self.app.root.after(200, poll)
                return
            if holder.winfo_exists():   # 窗口没被关、结果区没被新拖入的文件清掉
                self.show(box["res"], holder)
                holder.destroy()
        self.app.root.after(200, poll)

    # ------------------------------------------------------------ 结果卡片

    def card(self, before=None):
        c = self.app.ttk.Frame(self.results, style="Card.TFrame", padding=14)
        c.pack(fill="x", pady=(0, 10), **({"before": before} if before is not None else {}))
        return c

    def label(self, parent, text, color="text", size=11, bold=False, **kw):
        return self.app.ttk.Label(parent, text=text, foreground=C[color], font=(self.app.fam, size, "bold") if bold else (self.app.fam, size), **kw)

    def bad_card(self, name, why, before=None):
        c = self.card(before)
        self.label(c, "✗  " + name, "bad", bold=True).pack(anchor="w")
        self.label(c, why, wraplength=480).pack(anchor="w", pady=(4, 0))

    def ok_card(self, res, before=None):
        ttk = self.app.ttk
        c = self.card(before)
        head = ttk.Frame(c)
        head.pack(fill="x")
        self.label(head, "✓  转换好了", "ok", bold=True).pack(side="left")
        self.label(head, res["src_name"], "muted", 10).pack(side="right")
        self.label(c, res["summary"], "muted").pack(anchor="w", pady=(4, 0))
        for w in res["warnings"]:
            self.label(c, "注意: " + w, "warn", 10, wraplength=480).pack(anchor="w", pady=(4, 0))
        row = ttk.Frame(c)
        row.pack(fill="x", pady=10)
        entry = ttk.Entry(row)
        entry.insert(0, res["out_path"])
        entry.configure(state="readonly")
        entry.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="打开文件夹", command=lambda: open_folder(res["out_path"])).pack(side="left", padx=(8, 0))
        act = ttk.Frame(c)
        act.pack(fill="x")
        slot = self.app.tk.StringVar(value="存档 %d" % (res["slot"] or 1))
        if res["slot"] is not None:   # 战阵存档只有一个位置, 不选存档位
            ttk.Combobox(act, textvariable=slot, values=["存档 %d" % i for i in range(1, 6)], state="readonly", width=8).pack(side="left")
        status = self.label(c, "", "ok", 10, wraplength=480)
        ttk.Button(act, text="放进游戏", style="Accent.TButton", command=lambda: self.put(res, int(slot.get()[-1]), status)).pack(side="left", padx=(8, 0) if res["slot"] is not None else 0)
        status.pack(anchor="w", pady=(8, 0))

    def put(self, res, slot, status):
        app = self.app
        dst_dir = O.game_dir(res["kind_out"])
        if dst_dir is None:   # 原版游戏目录: 第一次问一次, 以后记住
            dst_dir = app.fd.askdirectory(title="选原版游戏所在的文件夹 (里面有 GD00.GSF 这类文件)")
            if not dst_dir:
                return
            O.remember("original_dir", dst_dir)
        try:
            try:
                done = O.place(res, dst_dir, slot)
            except SlotTaken:
                if not app.mb.askyesno("存档 %d 已有存档" % slot if res["slot"] is not None else "已有战阵存档", "替换它吗? 旧的会先自动备份。"):
                    status.configure(text="没有替换", foreground=C["muted"])
                    return
                done = O.place(res, dst_dir, slot, overwrite=True)
        except GsfError as e:
            status.configure(text="✗  " + str(e), foreground=C["bad"])
            return
        text = ("✓  已放进存档 %d: %s" % (slot, done["dst"])) if res["slot"] is not None else ("✓  已放进: " + done["dst"])
        if done["backup"]:
            text += "\n旧存档已备份: " + done["backup"]
        status.configure(text=text, foreground=C["ok"])


class App:
    def __init__(self, root, tk, ttk, filedialog, tkfont, messagebox, files=()):
        self.root, self.tk, self.ttk, self.fd, self.mb = root, tk, ttk, filedialog, messagebox
        root.title("天地劫 存档转换")
        load_theme(root)
        families = set(tkfont.families())
        self.fam = next((f for f in FONT_FAMILIES if f in families), tkfont.nametofont("TkDefaultFont").actual("family"))
        for name in tkfont.names(root):   # 主题自带的字体 (Segoe UI) 没有中文时统一换成能显示中文的
            try:
                tkfont.nametofont(name, root).configure(family=self.fam)
            except tk.TclError:
                pass
        self.dnd = load_dnd(root)
        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True, padx=12, pady=12)
        self.pages = [Page(self, nb, spec) for spec in PAGES]
        self.nb = nb
        if files:
            root.after(100, lambda: self.open_files(list(files)))

    def open_files(self, paths):
        """命令行/拖到脚本上给的文件: .GSF 去第一页, .json 去第二页。"""
        for page in self.pages:
            mine = [p for p in paths if p.lower().endswith((".gsf", ".gcf") if page.direction == O.TO_REPLICA else (".json",))]
            if mine:
                self.nb.select(page.frame)
                page.handle(mine)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    tk, ttk, fd, tkfont, mb = import_tk()
    try:
        root = tk.Tk()
    except tk.TclError as e:
        print("打不开图形界面 (%s)。没有桌面环境时请用命令行: import_gsf.py / export_gsf.py" % e, file=sys.stderr)
        return 1
    App(root, tk, ttk, fd, tkfont, mb, argv)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
