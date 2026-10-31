# SPDX-License-Identifier: GPL-3.0-only
"""save_names.py: 存档修改器的名字表 (解析 common_story.pck, 退回 content/tdj/data, 再退回只显示编号)。pck 现场拼, 不依赖资源。"""
import json
import os
import struct
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "saves"))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "savetool"))   # 独立的 SwordmanHD-SaveTool 仓库里源码在这里
import save_names as N  # noqa: E402

ITEMS = [{"id": 1, "name": "青钢剑", "type": 1, "equip_units": [0]}, {"id": 2, "name": "软革里衣", "type": 2, "equip_units": [0, 1]},
         {"id": 178, "name": "燧石", "type": 3, "equip_units": [0, 1]}, {"id": 225, "name": "返气丸", "type": 0, "equip_units": []}]
SKILLS = [{"id": 0, "name": "气愈之术"}, {"id": 42, "name": "千煌雷烈"}]
UNITS = [{"id": 0, "name": "殷剑平"}, {"id": 1, "name": "封寒月"}]


def make_pck(path, files):
    """最小的 Godot 4 pck (format 4, flags 2): 头 + 对齐的数据 + 目录。files {包内路径: bytes}。"""
    base = 128
    out = bytearray(b"\0" * base)
    entries = []
    for name, data in files.items():
        entries.append((name.encode("utf-8"), len(out) - base, len(data)))
        out += data + b"\0" * ((-len(data)) % 32)
    dir_off = len(out)
    out += struct.pack("<I", len(entries))
    for name, off, size in entries:
        pad = (-len(name)) % 4
        out += struct.pack("<I", len(name) + pad) + name + b"\0" * pad + struct.pack("<QQ", off, size) + b"\0" * 16 + struct.pack("<I", 0)
    out[0:40] = struct.pack("<4sIIIIIQQ", b"GDPC", 4, 4, 7, 2, 2, base, dir_off)
    with open(path, "wb") as f:
        f.write(out)


def pck_files():
    j = lambda v: json.dumps(v, ensure_ascii=False).encode("utf-8")
    return {"content/tdj/data/items.json": j(ITEMS), "content/tdj/data/skills.json": j(SKILLS), "content/tdj/data/units.json": j(UNITS),
            "content/tdj/locale/hant/data/items.json": j([{"id": 1, "name": "繁体"}]), "other/x.bin": b"abc"}


class PckTest(unittest.TestCase):
    def test_reads_only_files_under_the_prefix(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "common_story.pck")
            make_pck(p, pck_files())
            got = N.read_pck_files(p)
            self.assertEqual(sorted(got), ["items.json", "skills.json", "units.json"])
            self.assertEqual(json.loads(got["items.json"]), ITEMS)

    def test_not_a_pck_raises(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.pck")
            with open(p, "wb") as f:
                f.write(b"hello" * 20)
            with self.assertRaises(ValueError):
                N.read_pck_files(p)


class NamesTest(unittest.TestCase):
    def setUp(self):
        self.n = N.Names(ITEMS, SKILLS, UNITS)

    def test_names_and_missing_fall_back_to_number(self):
        self.assertEqual((self.n.item(178), self.n.skill(42), self.n.unit(1)), ("燧石", "千煌雷烈", "封寒月"))
        self.assertEqual((self.n.item(999), self.n.skill(999), self.n.unit(999)), ("#999", "#999", "#999"))

    def test_search_by_name_or_number(self):
        self.assertEqual(self.n.search_items("燧"), [(178, "燧石")])
        self.assertEqual(self.n.search_items("225"), [(225, "返气丸")])
        self.assertEqual(len(self.n.search_items("")), 4)

    def test_equippable_filters_type_and_unit(self):
        self.assertEqual(self.n.equippable("weapon", 0), [(1, "青钢剑")])
        self.assertEqual(self.n.equippable("weapon", 1), [])
        self.assertEqual(self.n.equippable("armor", 1), [(2, "软革里衣")])
        self.assertEqual(self.n.equippable("accessory", 0), [(178, "燧石")])

    def test_empty_names_are_unavailable(self):
        self.assertFalse(N.Names().available)
        self.assertTrue(self.n.available)


class LoadTest(unittest.TestCase):
    def test_pck_then_data_dir_then_empty(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "common_story.pck")
            make_pck(p, pck_files())
            self.assertEqual(N.load_names(pck=p).item(1), "青钢剑")
            data = os.path.join(d, "data")
            os.makedirs(data)
            for k, v in (("items", ITEMS), ("skills", SKILLS), ("units", UNITS)):
                with open(os.path.join(data, k + ".json"), "w", encoding="utf-8") as f:
                    json.dump(v, f, ensure_ascii=False)
            self.assertEqual(N.load_names(pck=os.path.join(d, "nope.pck"), data_dir=data).item(178), "燧石")
            self.assertFalse(N.load_names(pck=os.path.join(d, "nope.pck"), data_dir=os.path.join(d, "none")).available)

    def test_find_pck_looks_in_resource_folders(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "resource"))
            p = os.path.join(d, "resource", "common_story.pck")
            make_pck(p, pck_files())
            self.assertEqual(N.find_pck([d]), p)
            self.assertIsNone(N.find_pck([os.path.join(d, "empty")]))


if __name__ == "__main__":
    unittest.main()
