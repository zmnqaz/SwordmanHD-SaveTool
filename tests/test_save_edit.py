# SPDX-License-Identifier: GPL-3.0-only
"""save_edit.py: 存档修改器的逻辑层 (金钱 / 行囊 / 队员属性 / 装备 / 技能 / 随身物品, 读写与转回原版)。样本用 test_export_gsf.party_save()。"""
import copy
import glob
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "saves"))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "savetool"))   # 独立的 SwordmanHD-SaveTool 仓库里源码在这里
sys.path.insert(0, HERE)
import export_gsf as X  # noqa: E402
import import_gsf as G  # noqa: E402
import save_edit as E  # noqa: E402
import save_names as N  # noqa: E402
import test_export_gsf as TX  # noqa: E402
import test_save_names as TN  # noqa: E402

NAMES = N.Names(TN.ITEMS, TN.SKILLS, TN.UNITS)


def sample(**over):
    s = TX.party_save(**over)
    s["bag"] = [178, 178, 225, 1]
    return s


class SaveDirTest(unittest.TestCase):
    def test_default_save_dir_per_platform(self):
        self.assertEqual(E.default_save_dir("win32", {"APPDATA": "C:\\Users\\u\\AppData\\Roaming"}, "C:\\Users\\u"), os.path.join("C:\\Users\\u\\AppData\\Roaming", "SwordmanHD"))
        self.assertEqual(E.default_save_dir("darwin", {}, "HOME"), os.path.join("HOME", "Library", "Application Support", "SwordmanHD"))
        self.assertEqual(E.default_save_dir("linux", {}, "HOME"), os.path.join("HOME", ".local", "share", "SwordmanHD"))
        self.assertEqual(E.default_save_dir("linux", {"XDG_DATA_HOME": "XDG"}, "HOME"), os.path.join("XDG", "SwordmanHD"))

    def test_windows_without_appdata_uses_roaming_under_home(self):
        self.assertEqual(E.default_save_dir("win32", {}, "C:\\Users\\u"), os.path.join("C:\\Users\\u", "AppData", "Roaming", "SwordmanHD"))

    def test_existing_saves_lists_slots_in_order(self):
        with tempfile.TemporaryDirectory() as d:
            for n in ("save3.json", "save1.json", "save9.json", "battle.json", "save2.json.bak"):
                open(os.path.join(d, n), "w").close()
            self.assertEqual([(i, os.path.basename(p)) for i, p in E.existing_saves(d)], [(1, "save1.json"), (3, "save3.json")])
            self.assertEqual(E.existing_saves(os.path.join(d, "nope")), [])


class GoldTest(unittest.TestCase):
    def test_set_gold_in_range(self):
        s = sample()
        E.set_gold(s, "12345")
        self.assertEqual(s["gold"], 12345)
        E.set_gold(s, E.GOLD_MAX)
        self.assertEqual(s["gold"], 2147483647)

    def test_gold_out_of_range_or_not_a_number_is_refused(self):
        s = sample()
        for bad in (-1, E.GOLD_MAX + 1, "abc", "", 1.5, None, True, float("nan")):
            with self.assertRaises(E.EditError, msg=repr(bad)):
                E.set_gold(s, bad)
        self.assertEqual(s["gold"], 100)


class BagTest(unittest.TestCase):
    def test_counts_keep_first_seen_order(self):
        self.assertEqual(E.bag_counts(sample()), [(178, 2), (225, 1), (1, 1)])

    def test_add_remove_set_count(self):
        s = sample()
        E.bag_add(s, 225, 3, NAMES)
        self.assertEqual(s["bag"].count(225), 4)
        E.bag_remove(s, 178, 1)
        self.assertEqual(s["bag"].count(178), 1)
        E.bag_set_count(s, 178, 5, NAMES)
        self.assertEqual(s["bag"].count(178), 5)
        E.bag_set_count(s, 178, 0, NAMES)
        self.assertNotIn(178, s["bag"])

    def test_capacity_and_unknown_item_and_too_many_removed(self):
        s = sample()
        s["bag"] = [1] * 510
        with self.assertRaises(E.EditError):
            E.bag_add(s, 2, 3, NAMES)
        self.assertEqual(len(s["bag"]), 510)
        with self.assertRaises(E.EditError):
            E.bag_add(sample(), 999, 1, NAMES)
        with self.assertRaises(E.EditError):
            E.bag_remove(sample(), 178, 3)
        with self.assertRaises(E.EditError):
            E.bag_add(sample(), 1, 0, NAMES)

    def test_without_names_only_the_number_range_is_checked(self):
        s = sample()
        E.bag_add(s, 999, 1, None)
        self.assertIn(999, s["bag"])
        with self.assertRaises(E.EditError):
            E.bag_add(s, -2, 1, None)


class MemberTest(unittest.TestCase):
    def test_numeric_fields_become_ints(self):
        s = sample()
        for field, v in (("lv", "50"), ("exp", 7), ("hp_max", 3500), ("mp_max", 0), ("spirit_points", 9)):
            E.set_field(s, 0, field, v)
        p = s["party"]["0"]
        self.assertEqual((p["lv"], p["exp"], p["hp_max"], p["mp_max"], p["spirit_points"]), (50, 7, 3500, 0, 9))
        self.assertTrue(all(type(p[k]) is int for k in ("lv", "exp", "hp_max", "mp_max", "spirit_points")))

    def test_stats_and_spirit(self):
        s = sample()
        E.set_field(s, 0, "stat:str", 500)
        E.set_field(s, 0, "spirit:魔", 100)
        self.assertEqual(s["party"]["0"]["stats"]["str"], 500)
        self.assertEqual(s["party"]["0"]["spirit"]["魔"], 100)
        self.assertEqual(s["party"]["0"]["stats"]["int"], 12.0)   # 没改的不动

    def test_limits(self):
        s = sample()
        for field, bad in (("lv", 0), ("lv", 100), ("exp", -1), ("hp_max", 0), ("hp_max", 32768), ("mp_max", 32768), ("stat:vit", 501), ("spirit:迅", -1), ("spirit_points", 40000)):
            with self.assertRaises(E.EditError, msg=(field, bad)):
                E.set_field(s, 0, field, bad)
        with self.assertRaises(E.EditError):
            E.set_field(s, 0, "stat:xxx", 1)
        with self.assertRaises(E.EditError):
            E.set_field(s, 0, "lv", "x")
        self.assertEqual(s["party"]["0"]["lv"], 9.0)

    def test_unknown_member(self):
        with self.assertRaises(E.EditError):
            E.set_field(sample(), 5, "lv", 3)

    def test_gear_checks_slot_type_and_who_can_wear_it(self):
        s = sample()
        E.set_gear(s, 0, "weapon", 1, NAMES)
        E.set_gear(s, 0, "armor", 2, NAMES)
        E.set_gear(s, 0, "accessory", None, NAMES)
        self.assertEqual(s["party"]["0"]["gear"], {"weapon": 1, "armor": 2, "accessory": None})
        with self.assertRaises(E.EditError):
            E.set_gear(s, 0, "weapon", 2, NAMES)       # 护具放武器栏
        with self.assertRaises(E.EditError):
            E.set_gear(s, 0, "weapon", 999, NAMES)     # 不存在
        s["party"]["1"] = {"gear": {}}
        with self.assertRaises(E.EditError):
            E.set_gear(s, 1, "weapon", 1, NAMES)       # 青钢剑只有 0 号能装
        with self.assertRaises(E.EditError):
            E.set_gear(s, 0, "head", 1, NAMES)

    def test_slots_limit_and_ids(self):
        s = sample()
        E.set_slots(s, 0, "items", [178, 225], NAMES)
        E.set_slots(s, 0, "skills", [0, 42], NAMES)
        self.assertEqual((s["party"]["0"]["items"], s["party"]["0"]["skills"]), ([178, 225], [0, 42]))
        with self.assertRaises(E.EditError):
            E.set_slots(s, 0, "items", [1] * 11, NAMES)
        with self.assertRaises(E.EditError):
            E.set_slots(s, 0, "skills", [999], NAMES)
        with self.assertRaises(E.EditError):
            E.set_slots(s, 0, "items", [999], NAMES)
        with self.assertRaises(E.EditError):
            E.set_slots(s, 0, "bag", [1], NAMES)


class UntouchedTest(unittest.TestCase):
    def test_other_fields_are_not_changed(self):
        s = sample()
        before = copy.deepcopy(s)
        E.set_gold(s, 1)
        E.bag_add(s, 1, 1, NAMES)
        E.set_field(s, 0, "lv", 10)
        for k in ("game_data", "content", "time", "version", "stage", "next_stage", "camp", "seeded", "where"):
            self.assertEqual(s[k], before[k], k)


class FileTest(unittest.TestCase):
    def write(self, d, s, name="save1.json"):
        p = os.path.join(d, name)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False)
        return p

    def test_load_rejects_non_saves(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "save1.json")
            for text in ("[]", "{}", '{"gold": 1, "bag": 3, "party": {}}', "not json"):
                with open(p, "w", encoding="utf-8") as f:
                    f.write(text)
                with self.assertRaises(E.EditError, msg=text):
                    E.load(p)

    def test_save_backs_up_old_file_and_writes_new(self):
        with tempfile.TemporaryDirectory() as d:
            p = self.write(d, sample())
            with open(p, encoding="utf-8") as f:
                old = f.read()
            s = E.load(p)
            E.set_gold(s, 777)
            bak = E.save(p, s)
            with open(bak, encoding="utf-8") as f:
                self.assertEqual(f.read(), old)
            self.assertEqual(E.load(p)["gold"], 777)
            self.assertEqual(len(glob.glob(p + ".tmp*")), 0)

    def test_failed_write_keeps_the_original(self):
        with tempfile.TemporaryDirectory() as d:
            p = self.write(d, sample())
            s = E.load(p)
            os.mkdir(p + ".tmp-import")   # 临时文件的位置被目录占了: 写不进去
            with self.assertRaises(E.EditError):
                E.save(p, s)
            self.assertEqual(E.load(p)["gold"], 100)

    def test_edited_save_still_converts_to_original_and_back(self):
        s = sample()
        E.set_gold(s, 99999)
        E.bag_add(s, 225, 2, NAMES)
        E.set_field(s, 0, "lv", 99)
        E.set_field(s, 0, "hp_max", 32767)
        E.set_field(s, 0, "stat:luk", 500)
        raw, _ = X.build_gsf(s)
        back = G.parse_gsf(raw)["state"]
        self.assertEqual(back["gold"], 99999)
        self.assertEqual(back["bag"].count(225), 3)
        p = back["party"]["0"]
        self.assertEqual((p["lv"], p["hp_max"], p["stats"]["luk"]), (99, 32767, 500))


if __name__ == "__main__":
    unittest.main()
