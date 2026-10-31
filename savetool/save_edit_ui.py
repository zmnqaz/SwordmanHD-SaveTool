# SPDX-License-Identifier: GPL-3.0-only
"""「修改存档」页 (存档工具 save_tool.py 的第三页): 打开 / 拖入复刻版 saveN.json, 改金钱、行囊、队员属性 / 装备 / 技能 / 随身物品, 保存。
只有界面; 校验、读写在 save_edit.py, 名字表在 save_names.py。出错在页顶红字提示, 不弹窗; 改动要点「保存」才写进文件 (保存前旧档自动备份)。"""
import os
import re

import save_edit as E

SLOT_NAMES = (("weapon", "武器"), ("armor", "护具"), ("accessory", "饰物"))
EMPTY = "（空）"
FIELD_ROWS = (("lv", "等级"), ("exp", "经验"), ("hp_max", "HP 上限"), ("mp_max", "MP 上限"), ("spirit_points", "五魂点"))
STAT_ROWS = (("stat:str", "力"), ("stat:int", "智"), ("stat:avg", "敏"), ("stat:vit", "体"), ("stat:luk", "运"))
SPIRIT_ROWS = tuple(("spirit:" + k, k) for k in E.SPIRIT_KEYS)


def label_for(table_name, i):
    return "%s (#%d)" % (table_name, i)


def parse_id(text):
    """「燧石 (#178)」「#178」「178」 -> 178; 认不出返回 None。"""
    m = re.search(r"#(\d+)\)?\s*$", text) or re.fullmatch(r"\s*(\d+)\s*", text)
    return int(m.group(1)) if m else None


class SlotEditor:
    """一个最多 10 格的编号列表 (技能 / 随身物品): 左边是现有的, 右边搜名字添加, 点「应用」写进队员记录。"""

    def __init__(self, page, parent, title, search, name_of, on_apply):
        tk, ttk = page.app.tk, page.app.ttk
        self.page, self.search, self.name_of, self.values, self.hits = page, search, name_of, [], []
        self.box = ttk.LabelFrame(parent, text=title, padding=8)
        font = (page.app.fam, 10)
        self.cur = tk.Listbox(self.box, height=5, width=20, exportselection=False, font=font)
        self.cur.grid(row=0, column=0, rowspan=4, sticky="ns")
        ttk.Button(self.box, text="移除选中", command=self.remove).grid(row=4, column=0, sticky="we", pady=(4, 0))
        ttk.Label(self.box, text="搜名字或编号：", foreground=page.app.C["muted"], font=(page.app.fam, 9)).grid(row=0, column=1, padx=(10, 0), sticky="w")
        self.q = tk.StringVar()
        ttk.Entry(self.box, textvariable=self.q, width=14).grid(row=1, column=1, padx=(10, 0), sticky="we")
        self.res = tk.Listbox(self.box, height=4, width=20, exportselection=False, font=font)
        self.res.grid(row=2, column=1, rowspan=2, padx=(10, 0), sticky="ns")
        self.res.bind("<Double-Button-1>", lambda e: self.add())
        ttk.Button(self.box, text="← 添加", command=self.add).grid(row=4, column=1, sticky="we", padx=(10, 0), pady=(4, 0))
        ttk.Button(self.box, text="应用到这个人", style="Accent.TButton", command=lambda: on_apply(list(self.values))).grid(row=5, column=0, columnspan=2, sticky="we", pady=(8, 0))
        self.q.trace_add("write", lambda *a: self.fill())
        self.fill()

    def load(self, values):
        self.values = [int(v) for v in values]
        self.show()

    def show(self):
        self.cur.delete(0, "end")
        for v in self.values:
            self.cur.insert("end", label_for(self.name_of(v), v))

    def fill(self):
        self.hits = self.search(self.q.get())[:300]
        self.res.delete(0, "end")
        for i, n in self.hits:
            self.res.insert("end", label_for(n, i))

    def add(self):
        sel = self.res.curselection()
        i = self.hits[sel[0]][0] if sel else (int(self.q.get()) if self.q.get().strip().isdigit() else None)
        if i is None:
            self.page.say("先在右边搜一个名字再点选, 或者直接输入编号", "warn")
        elif len(self.values) >= E.SLOTS:
            self.page.say("最多 %d 格, 先移除一个" % E.SLOTS, "bad")
        else:
            self.values.append(i)
            self.show()

    def remove(self):
        for k in reversed(self.cur.curselection()):
            del self.values[k]
        self.show()


class EditPage:
    def __init__(self, app, nb, names, find_pck):
        self.app, self.names, self.find_pck = app, names, find_pck
        self.d = self.path = None
        self.dirty = False
        tk, ttk = app.tk, app.ttk
        self.frame = ttk.Frame(nb, padding=14)
        nb.add(self.frame, text="修改存档")
        top = ttk.Frame(self.frame)
        top.pack(fill="x")
        ttk.Button(top, text="打开存档…", command=self.pick).pack(side="left")
        self.path_var = tk.StringVar(value="（把 save1.json ~ save5.json 拖进来, 或点左边的按钮）" if app.dnd else "（点左边的按钮选 save1.json ~ save5.json）")
        e = ttk.Entry(top, textvariable=self.path_var, state="readonly")
        e.pack(side="left", fill="x", expand=True, padx=8)
        self.save_btn = ttk.Button(top, text="保存", style="Accent.TButton", command=self.save, state="disabled")
        self.save_btn.pack(side="left")
        self.saveas_btn = ttk.Button(top, text="另存为…", command=self.save_as, state="disabled")
        self.saveas_btn.pack(side="left", padx=(6, 0))
        self.status = ttk.Label(self.frame, text="", font=(app.fam, 10), wraplength=700, justify="left")
        self.status.pack(fill="x", pady=(8, 6), anchor="w")
        self.inner = ttk.Notebook(self.frame)
        self.inner.pack(fill="both", expand=True)
        self.build_basic()
        self.build_bag()
        self.build_team()
        if app.dnd:
            for w in (self.frame, e):
                w.drop_target_register(app.dnd)
                w.dnd_bind("<<Drop>>", lambda ev: self.open(next((p for p in app.root.tk.splitlist(ev.data)), None)))
        self.report_names()

    # ------------------------------------------------------------ 公共

    def say(self, text, kind="muted"):
        self.status.configure(text=text, foreground=self.app.C[kind])

    def report_names(self):
        if self.names.available:
            self.say("已读到物品 / 技能 / 人物名字表, 可以按名字搜索。", "muted")
        else:
            self.say("没有找到资源包 common_story.pck: 现在只能按编号改, 也不检查装备能不能装。把它放在工具旁边的 resource 文件夹里再重开, 或点「选择资源包」。", "warn")
            self.pck_btn = self.app.ttk.Button(self.frame, text="选择资源包…", command=self.choose_pck)
            self.pck_btn.pack(anchor="w", before=self.inner)

    def choose_pck(self):
        p = self.app.fd.askopenfilename(title="选 common_story.pck", filetypes=[("资源包", "*.pck")])
        if p:
            self.names = self.find_pck(p)
            if self.names.available:
                self.pck_btn.destroy()
                self.rebuild_pickers()
                self.report_names()
            else:
                self.say("这个文件里没读到名字表, 换一个 common_story.pck", "bad")

    def guarded(self, fn, done=""):
        """跑一次修改: 校验失败红字提示 (数据不变), 成功标记「未保存」并刷新。"""
        if self.d is None:
            self.say("先打开一个存档", "warn")
            return
        try:
            fn()
        except E.EditError as e:
            self.say("✗  " + str(e), "bad")
            return
        self.dirty = True
        self.save_btn.configure(text="保存 *")
        self.say("✓  " + (done or "已改, 记得点「保存」") + "  (还没写进文件, 点「保存」才生效)", "ok")
        self.refresh()

    def pick(self):
        p = self.app.fd.askopenfilename(title="选择复刻版存档", filetypes=[("复刻版存档", "*.json"), ("所有文件", "*")])
        if p:
            self.open(p)

    def open(self, path):
        if not path:
            return
        if self.dirty and not self.app.mb.askyesno("有没保存的改动", "丢掉当前存档里没保存的改动, 打开新的吗?"):
            return
        try:
            self.d = E.load(path)
        except E.EditError as e:
            self.say("✗  " + str(e), "bad")
            return
        self.path = path
        self.path_var.set(path)
        self.dirty = False
        self.save_btn.configure(text="保存", state="normal")
        self.saveas_btn.configure(state="normal")
        self.app.nb.select(self.frame)
        self.say("已打开。改完点「保存」, 旧存档会先自动备份。", "muted")
        self.refresh()

    def save(self, path=None):
        if self.d is None:
            return
        target = path or self.path
        try:
            bak = E.save(target, self.d)
        except E.EditError as e:
            self.say("✗  " + str(e), "bad")
            return
        self.path = target
        self.path_var.set(target)
        self.dirty = False
        self.save_btn.configure(text="保存")
        self.say("✓  已保存: %s" % target + ("\n旧存档已备份: " + bak if bak else ""), "ok")

    def save_as(self):
        p = self.app.fd.asksaveasfilename(title="另存为", defaultextension=".json", initialfile=os.path.basename(self.path or "save1.json"), filetypes=[("复刻版存档", "*.json")])
        if p:
            self.save(p)

    def refresh(self):
        self.refresh_basic()
        self.refresh_bag()
        self.refresh_team()

    def rebuild_pickers(self):
        self.refresh_bag()
        self.refresh_team()

    # ------------------------------------------------------------ 基本

    def build_basic(self):
        tk, ttk = self.app.tk, self.app.ttk
        f = ttk.Frame(self.inner, padding=16)
        self.inner.add(f, text="基本")
        ttk.Label(f, text="金钱 (两)").grid(row=0, column=0, sticky="w")
        self.gold = tk.StringVar()
        ttk.Entry(f, textvariable=self.gold, width=14).grid(row=0, column=1, padx=8)
        ttk.Button(f, text="应用", style="Accent.TButton", command=lambda: self.guarded(lambda: E.set_gold(self.d, self.gold.get()), "金钱已改")).grid(row=0, column=2)
        ttk.Label(f, text="范围 0 ~ %d" % E.GOLD_MAX, foreground=self.app.C["muted"]).grid(row=0, column=3, padx=10)
        self.summary = ttk.Label(f, text="", foreground=self.app.C["muted"])
        self.summary.grid(row=1, column=0, columnspan=4, sticky="w", pady=(16, 0))

    def refresh_basic(self):
        self.gold.set(str(int(self.d["gold"])))
        self.summary.configure(text="队员 %d 人, 行囊 %d / %d 件" % (len(self.d["party"]), len(self.d["bag"]), E.BAG_SLOTS))

    # ------------------------------------------------------------ 行囊

    def build_bag(self):
        tk, ttk = self.app.tk, self.app.ttk
        f = ttk.Frame(self.inner, padding=10)
        self.inner.add(f, text="行囊")
        ttk.Style().configure("Treeview", font=(self.app.fam, 10), rowheight=24)
        left = ttk.Frame(f)
        left.pack(side="left", fill="both", expand=True)
        self.tree = ttk.Treeview(left, columns=("name", "id", "count"), show="headings", height=14, selectmode="browse")
        for c, t, w in (("name", "物品", 200), ("id", "编号", 60), ("count", "数量", 60)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="w" if c == "name" else "e")
        sb = ttk.Scrollbar(left, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.bag_selected())
        right = ttk.Frame(f, padding=(14, 0, 0, 0))
        right.pack(side="left", fill="y")
        ttk.Label(right, text="选中的物品").pack(anchor="w")
        self.bag_cur = ttk.Label(right, text="（先在左边点一行）", foreground=self.app.C["muted"])
        self.bag_cur.pack(anchor="w")
        row = ttk.Frame(right)
        row.pack(anchor="w", pady=6)
        self.bag_n = tk.StringVar()
        ttk.Entry(row, textvariable=self.bag_n, width=6).pack(side="left")
        ttk.Button(row, text="设置数量", command=self.bag_set).pack(side="left", padx=6)
        ttk.Button(row, text="全部删除", command=lambda: self.bag_set(0)).pack(side="left")
        ttk.Separator(right).pack(fill="x", pady=10)
        ttk.Label(right, text="加入新物品 (搜名字或输入编号)").pack(anchor="w")
        self.bag_q = tk.StringVar()
        ttk.Entry(right, textvariable=self.bag_q, width=22).pack(anchor="w", pady=4)
        self.bag_res = tk.Listbox(right, height=8, width=26, exportselection=False, font=(self.app.fam, 10))
        self.bag_res.pack(anchor="w")
        self.bag_res.bind("<Double-Button-1>", lambda e: self.bag_add())
        self.bag_hits = []
        self.bag_q.trace_add("write", lambda *a: self.bag_fill())
        row2 = ttk.Frame(right)
        row2.pack(anchor="w", pady=6)
        self.bag_add_n = tk.StringVar(value="1")
        ttk.Entry(row2, textvariable=self.bag_add_n, width=6).pack(side="left")
        ttk.Button(row2, text="加入行囊", style="Accent.TButton", command=self.bag_add).pack(side="left", padx=6)
        self.bag_fill()

    def bag_fill(self):
        self.bag_hits = self.names.search_items(self.bag_q.get())[:300] if self.names.available else []
        self.bag_res.delete(0, "end")
        for i, n in self.bag_hits:
            self.bag_res.insert("end", label_for(n, i))

    def refresh_bag(self):
        self.bag_fill()
        self.tree.delete(*self.tree.get_children())
        for i, n in E.bag_counts(self.d):
            self.tree.insert("", "end", iid=str(i), values=(self.names.item(i), i, n))
        self.bag_cur.configure(text="（先在左边点一行）")

    def bag_selected(self):
        sel = self.tree.selection()
        if sel:
            i = int(sel[0])
            self.bag_cur.configure(text=label_for(self.names.item(i), i))
            self.bag_n.set(str(self.tree.item(sel[0], "values")[2]))

    def bag_set(self, n=None):
        sel = self.tree.selection()
        if not sel:
            self.say("先在左边点一行物品", "warn")
            return
        i, count = int(sel[0]), self.bag_n.get() if n is None else n
        self.guarded(lambda: E.bag_set_count(self.d, i, count, self.names), "行囊已改")

    def bag_add(self):
        sel = self.bag_res.curselection()
        q = self.bag_q.get().strip()
        i = self.bag_hits[sel[0]][0] if sel else (int(q) if q.isdigit() else None)
        if i is None:
            self.say("先在列表里点选一个物品, 或者直接输入编号", "warn")
            return
        self.guarded(lambda: E.bag_add(self.d, i, self.bag_add_n.get(), self.names), "已加入行囊")

    # ------------------------------------------------------------ 队员

    def build_team(self):
        tk, ttk = self.app.tk, self.app.ttk
        f = ttk.Frame(self.inner, padding=10)
        self.inner.add(f, text="队员")
        self.uids = []
        self.members = tk.Listbox(f, width=14, height=18, exportselection=False, font=(self.app.fam, 11))
        self.members.pack(side="left", fill="y")
        self.members.bind("<<ListboxSelect>>", lambda e: self.member_selected())
        body = ttk.Frame(f, padding=(14, 0, 0, 0))
        body.pack(side="left", fill="both", expand=True)
        attrs = ttk.LabelFrame(body, text="属性", padding=8)
        attrs.pack(fill="x")
        self.vars = {}
        for r, rows in enumerate((FIELD_ROWS, STAT_ROWS, SPIRIT_ROWS)):
            for c, (key, text) in enumerate(rows):
                ttk.Label(attrs, text=text).grid(row=r * 2, column=c, sticky="w", padx=4)
                self.vars[key] = tk.StringVar()
                ttk.Entry(attrs, textvariable=self.vars[key], width=8).grid(row=r * 2 + 1, column=c, padx=4, pady=(0, 4))
        ttk.Button(attrs, text="应用属性", style="Accent.TButton", command=self.apply_attrs).grid(row=0, column=6, rowspan=2, padx=10)
        ttk.Label(attrs, text="等级 1~99  属性 0~500  HP/MP 上限 ≤ 32767", foreground=self.app.C["muted"], font=(self.app.fam, 9)).grid(row=6, column=0, columnspan=7, sticky="w", padx=4)
        gear = ttk.LabelFrame(body, text="装备", padding=8)
        gear.pack(fill="x", pady=8)
        self.gear = {}
        for c, (slot, text) in enumerate(SLOT_NAMES):
            ttk.Label(gear, text=text).grid(row=0, column=c, sticky="w", padx=4)
            self.gear[slot] = ttk.Combobox(gear, width=18)
            self.gear[slot].grid(row=1, column=c, padx=4)
        ttk.Button(gear, text="应用装备", style="Accent.TButton", command=self.apply_gear).grid(row=1, column=3, padx=10)
        lists = ttk.Frame(body)
        lists.pack(fill="x")
        self.skills = SlotEditor(self, lists, "技能 (最多 10)", lambda q: self.names.search_skills(q), self.names_skill, lambda v: self.apply_slots("skills", v))
        self.items = SlotEditor(self, lists, "随身物品 (最多 10)", lambda q: self.names.search_items(q), self.names_item, lambda v: self.apply_slots("items", v))
        self.skills.box.pack(side="left", padx=(0, 8))
        self.items.box.pack(side="left")

    def names_skill(self, i):
        return self.names.skill(i)

    def names_item(self, i):
        return self.names.item(i)

    def refresh_team(self):
        keep = self.current_uid()
        self.uids = [u for u, _ in E.members(self.d)]
        self.members.delete(0, "end")
        for u in self.uids:
            self.members.insert("end", "%d  %s" % (u, self.names.unit(u)))
        if self.uids:
            k = self.uids.index(keep) if keep in self.uids else 0
            self.members.selection_set(k)
            self.member_selected()
        self.skills.fill()
        self.items.fill()

    def current_uid(self):
        sel = self.members.curselection()
        return self.uids[sel[0]] if sel and sel[0] < len(self.uids) else None

    def member_selected(self):
        uid = self.current_uid()
        if uid is None:
            return
        p = dict(E.members(self.d))[uid]
        for key, _ in FIELD_ROWS:
            self.vars[key].set(str(int(p.get(key, 0))))
        for key, _ in STAT_ROWS:
            self.vars[key].set(str(int((p.get("stats") or {}).get(key[5:], 0))))
        for key, _ in SPIRIT_ROWS:
            self.vars[key].set(str(int((p.get("spirit") or {}).get(key[7:], 0))))
        gear = p.get("gear") or {}
        for slot, _ in SLOT_NAMES:
            cur = gear.get(slot)
            opts = [label_for(n, i) for i, n in self.names.equippable(slot, uid)] if self.names.available else []
            if cur is not None and label_for(self.names.item(int(cur)), int(cur)) not in opts:
                opts.insert(0, label_for(self.names.item(int(cur)), int(cur)))
            self.gear[slot].configure(values=[EMPTY] + opts)
            self.gear[slot].set(EMPTY if cur is None else label_for(self.names.item(int(cur)), int(cur)))
        self.skills.load(p.get("skills") or [])
        self.items.load(p.get("items") or [])

    def apply_attrs(self):
        uid = self.current_uid()

        def go():
            rec = dict(E.members(self.d))[uid]
            for key, _ in FIELD_ROWS + STAT_ROWS + SPIRIT_ROWS:
                text = self.vars[key].get().strip()
                if text == str(int(self.current_value(rec, key))):
                    continue   # 没动的不校验 (原存档里可能本来就超出现在的范围)
                E.set_field(self.d, uid, key, text)
        self.guarded(go, "属性已改")

    @staticmethod
    def current_value(rec, key):
        if key.startswith("stat:"):
            return (rec.get("stats") or {}).get(key[5:], 0)
        if key.startswith("spirit:"):
            return (rec.get("spirit") or {}).get(key[7:], 0)
        return rec.get(key, 0)

    def apply_gear(self):
        uid = self.current_uid()

        def go():
            rec = dict(E.members(self.d))[uid]
            for slot, _ in SLOT_NAMES:
                text = self.gear[slot].get().strip()
                i = None if text in ("", EMPTY) else parse_id(text)
                if i is None and text not in ("", EMPTY):
                    raise E.EditError("看不懂装备栏里填的 %r (请从下拉里选, 或填编号)" % text)
                old = (rec.get("gear") or {}).get(slot)
                if (None if old is None else int(old)) == i:
                    continue   # 没动的不校验
                E.set_gear(self.d, uid, slot, i, self.names)
        self.guarded(go, "装备已改")

    def apply_slots(self, key, values):
        uid = self.current_uid()
        self.guarded(lambda: E.set_slots(self.d, uid, key, values, self.names), "技能已改" if key == "skills" else "随身物品已改")
