# SPDX-License-Identifier: GPL-3.0-only
"""存档修改器的名字表 (不依赖 tkinter): 物品 / 技能 / 人物的编号 -> 名字, 以及「这件物品这个人能不能装」。

来源按顺序试: 资源包 common_story.pck (Godot pck, 文件原样排放, 这里只读目录取 content/tdj/data/ 下的三个 json, 不需要 Godot)
→ game/content/tdj/data (有完整仓库时) → 程序自带的精简名字表 save_names_data.py (只有名字、类型、谁能装; make_names_data.py 生成)。\n都没有才是空表 (界面只显示编号, 不做名字/装备校验)。
"""
import json
import os
import struct

PREFIX = "content/tdj/data/"
PCK_NAME = "common_story.pck"
GEAR_TYPE = {"weapon": 1, "armor": 2, "accessory": 3}   # items.json 的 type: 1 武器 2 护具 3 饰物 0 道具


def read_pck_files(path, prefix=PREFIX):
    """{去掉 prefix 的包内路径: 字节} (pck format 4, flags 2: 偏移相对数据区起点, 与 Godot 4.7 一致); 不是这种 pck 抛 ValueError。"""
    with open(path, "rb") as f:
        head = f.read(40)
        if len(head) < 40 or head[:4] != b"GDPC":
            raise ValueError("%s 不是 Godot 资源包" % path)
        _, fmt, _, _, _, flags, file_base, dir_offset = struct.unpack("<4sIIIIIQQ", head)
        if fmt != 4 or flags != 2:
            raise ValueError("%s 的格式 (v%d, flags %d) 读不了" % (path, fmt, flags))
        f.seek(dir_offset)
        n, = struct.unpack("<I", f.read(4))
        found = {}
        for _ in range(n):
            plen, = struct.unpack("<I", f.read(4))
            name = f.read(plen).rstrip(b"\0").decode("utf-8")
            off, size = struct.unpack("<QQ", f.read(16))
            f.read(20)   # MD5 16 字节 + flags 4 字节
            if name.startswith(prefix):
                found[name[len(prefix):]] = (file_base + off, size)
        out = {}
        for name, (off, size) in found.items():
            f.seek(off)
            out[name] = f.read(size)
    return out


class Names:
    def __init__(self, items=(), skills=(), units=()):
        self.items = {r["id"]: r for r in items}
        self.skills = {r["id"]: r for r in skills}
        self.units = {r["id"]: r for r in units}

    @property
    def available(self):
        return bool(self.items)

    @staticmethod
    def _name(table, i):
        row = table.get(i)
        return row["name"] if row else "#%d" % i

    def item(self, i):
        return self._name(self.items, i)

    def skill(self, i):
        return self._name(self.skills, i)

    def unit(self, i):
        return self._name(self.units, i)

    def search_items(self, query):
        """名字含 query 或编号等于 query 的物品 [(编号, 名字)]; 空查询返回全部。"""
        q = query.strip()
        return [(i, r["name"]) for i, r in sorted(self.items.items()) if not q or q in r["name"] or q == str(i)]

    def search_skills(self, query):
        q = query.strip()
        return [(i, r["name"]) for i, r in sorted(self.skills.items()) if not q or q in r["name"] or q == str(i)]

    def equippable(self, slot, uid):
        """某个装备栏 (weapon / armor / accessory) 里这个人能装的物品 [(编号, 名字)]。"""
        t = GEAR_TYPE[slot]
        return [(i, r["name"]) for i, r in sorted(self.items.items()) if r.get("type") == t and int(uid) in r.get("equip_units", [])]


def _tables(files):
    def rows(key):
        try:
            return json.loads(files[key + ".json"].decode("utf-8"))
        except (KeyError, ValueError):
            return []
    return Names(rows("items"), rows("skills"), rows("units"))


def embedded_names():
    """程序自带的精简名字表 (save_names_data.py, 没有说明文字和数值); 缺了这个文件返回空表。"""
    try:
        import save_names_data as D
    except ImportError:
        return Names()
    return Names([{"id": i, "name": n, "type": t, "equip_units": list(u)} for i, n, t, u in D.ITEMS],
                 [{"id": i, "name": n} for i, n in D.SKILLS], [{"id": i, "name": n} for i, n in D.UNITS])


def load_names(pck=None, data_dir=None, fallback=True):
    """按 pck → data_dir → 内置名字表 (fallback=False 时不用) 的顺序读; 都没有返回空表。"""
    if pck and os.path.isfile(pck):
        try:
            names = _tables(read_pck_files(pck))
            if names.available:
                return names
        except (OSError, ValueError):
            pass
    if data_dir and os.path.isdir(data_dir):
        files = {}
        for k in ("items", "skills", "units"):
            try:
                with open(os.path.join(data_dir, k + ".json"), "rb") as f:
                    files[k + ".json"] = f.read()
            except OSError:
                pass
        names = _tables(files)
        if names.available:
            return names
    return embedded_names() if fallback else Names()


def find_pck(dirs):
    """在这些目录 (及其下的 resource/) 里找 common_story.pck, 找不到返回 None。"""
    for d in dirs:
        for p in (os.path.join(d, "resource", PCK_NAME), os.path.join(d, PCK_NAME)):
            if os.path.isfile(p):
                return p
    return None


def default_search_dirs(tool_dir):
    """工具所在目录往上几层 (资源包常放在工具旁边的 resource 文件夹里)。"""
    out, d = [], os.path.abspath(tool_dir)
    for _ in range(5):
        out.append(d)
        d = os.path.dirname(d)
    return out
