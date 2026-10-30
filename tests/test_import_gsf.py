# SPDX-License-Identifier: GPL-3.0-only
"""tools/saves/import_gsf.py: XOR、头解析、各字段偏移 (现场合成 GSF 字节, 不入库二进制)、坏文件、覆盖保护/备份、目录批量、dry-run、退出码。
与游戏侧 CampScene.import_gsf 的逐字段交叉验证在 game/tests/test_import_gsf.gd。"""
import base64
import datetime
import json
import os
import re
import struct
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
REPO = os.path.dirname(TOOLS)
sys.path.insert(0, os.path.join(TOOLS, "saves"))
sys.path.insert(0, os.path.join(TOOLS, "savetool"))   # 独立的 SwordmanHD-SaveTool 仓库里源码在这里
import import_gsf as G  # noqa: E402


def make_gsf(camp=3, level=7, next_stage=4, gold=1234, game_data=None, bag=(), party=(), date=b"10/04/26", time=b"17:30:00"):
    """合成一份营地存档字节。party: [dict(rec=记录号, uid, lv, ..., on=在队标志)]。"""
    head = struct.pack("<ii", camp, level) + date.ljust(9, b"\0") + time.ljust(9, b"\0")
    d = bytearray(G.BODY_SIZE)
    struct.pack_into("<i", d, 0, next_stage)
    struct.pack_into("<i", d, 8, gold)
    for k, v in (game_data or {}).items():
        struct.pack_into("<i", d, 0x1C + 4 * k, v)
    for i in range(512):
        struct.pack_into("<i", d, 0x71C + 4 * i, bag[i] if i < len(bag) else -1)
    for p in party:
        o = 0x21C + 80 * p["rec"]
        struct.pack_into("<hhhhh", d, o, p["uid"], p.get("lv", 1), p.get("exp", 0), p.get("hp", 50), p.get("mp", 20))
        struct.pack_into("<5h", d, o + 0xA, *p.get("stats", (11, 12, 13, 14, 15)))
        struct.pack_into("<5h", d, o + 0x14, *p.get("spirit", (1, 2, 3, 4, 5)))
        struct.pack_into("<3h", d, o + 0x1E, *p.get("gear", (-1, -1, -1)))
        struct.pack_into("<h", d, o + 0x24, p.get("on", 1))
        struct.pack_into("<h", d, o + 0x26, p.get("points", 9))
        items = list(p.get("items", [])) + [-1] * 10
        skills = list(p.get("skills", [])) + [-1] * 10
        struct.pack_into("<10h", d, o + 0x28, *items[:10])
        struct.pack_into("<10h", d, o + 0x3C, *skills[:10])
    return head + G.xor_body(bytes(d))


HERO = dict(rec=0, uid=0, lv=7, exp=33, hp=120, mp=44, stats=(21, 22, 23, 24, 25), spirit=(5, 4, 3, 2, 1),
            gear=(100, -1, 200), points=6, items=[100, 55, 200], skills=[1, 2, 3])


class Quiet:
    def __init__(self):
        self.lines = []

    def __call__(self, s=""):
        self.lines.append(str(s))

    @property
    def text(self):
        return "\n".join(self.lines)


class XorHeaderTest(unittest.TestCase):
    def test_xor_is_involution_and_uses_0xa5(self):
        self.assertEqual(G.xor_body(b"\x00\xa5\xff"), b"\xa5\x00\x5a")
        data = bytes(range(256))
        self.assertEqual(G.xor_body(G.xor_body(data)), data)

    def test_header_fields(self):
        raw = make_gsf(camp=22, level=63, date=b"01/09/16", time=b"23:14:27")
        h = G.parse_header(raw)
        self.assertEqual((h["camp_no"], h["level"], h["date"], h["time"]), (22, 63, "01/09/16", "23:14:27"))
        self.assertEqual(G.HEADER_SIZE, 4 + 4 + 9 + 9)
        self.assertEqual(G.GSF_SIZE, 3898)

    def test_header_too_short(self):
        with self.assertRaises(G.GsfError):
            G.parse_header(b"\0" * 25)


class FieldTest(unittest.TestCase):
    def test_global_fields(self):
        raw = make_gsf(camp=22, next_stage=24, gold=422, game_data={0: 5, 17: -3, 127: 9}, bag=[7, 8, 9], party=[HERO])
        s = G.parse_gsf(raw)["state"]
        self.assertEqual((s["camp"], s["stage"], s["next_stage"], s["gold"]), (22, 22, 24, 422))
        self.assertEqual(s["game_data"], {"0": 5, "17": -3, "127": 9})   # 0 的变量不记 (与 import_gsf 一致)
        self.assertEqual(s["bag"], [7, 8, 9])

    def test_bag_skips_empty_and_keeps_order(self):
        raw = make_gsf(bag=[5, 5, 300, 0])
        self.assertEqual(G.parse_gsf(raw)["state"]["bag"], [5, 5, 300, 0])   # 物品 0 是真物品, 只有 <0 才是空格

    def test_party_record(self):
        s = G.parse_gsf(make_gsf(party=[HERO]))["state"]
        self.assertEqual(s["party"]["0"], {
            "lv": 7, "exp": 33, "hp_max": 120, "mp_max": 44,
            "stats": {"str": 21, "int": 22, "avg": 23, "vit": 24, "luk": 25},
            "gear": {"weapon": 100, "armor": None, "accessory": 200}, "skills": [1, 2, 3],
            "spirit": {"迅": 5, "烈": 4, "神": 3, "魔": 2, "魂": 1}, "spirit_points": 6, "items": [100, 55, 200]})
        self.assertEqual(s["seeded"], [0])

    def test_only_flag_one_counts_and_record_order_kept(self):
        party = [dict(rec=0, uid=0), dict(rec=1, uid=4), dict(rec=2, uid=2, on=0), dict(rec=3, uid=3), dict(rec=9, uid=1, on=2)]
        s = G.parse_gsf(make_gsf(party=party))["state"]
        self.assertEqual(list(s["party"]), ["0", "4", "3"])   # 在队标志 != 1 的不导入 (不净散人 +0x24 = 0), 顺序按记录
        self.assertEqual(s["seeded"], [0, 4, 3])

    def test_negative_values_and_item_slots_capped_at_ten(self):
        hero = dict(HERO, items=list(range(30, 40)), skills=[-1, 5, -1, 6])
        p = G.parse_gsf(make_gsf(party=[hero]))["state"]["party"]["0"]
        self.assertEqual(p["items"], list(range(30, 40)))
        self.assertEqual(p["skills"], [5, 6])

    def test_missing_hero_warns(self):
        info = G.parse_gsf(make_gsf(party=[dict(rec=0, uid=3)]))
        self.assertTrue(any("殷剑平" in w for w in info["warnings"]))

    def test_trailing_bytes_ignored_with_warning(self):
        info = G.parse_gsf(make_gsf(party=[HERO]) + b"\1" * 40)
        self.assertEqual(info["state"]["gold"], 1234)
        self.assertTrue(info["warnings"])

    def test_real_fixture_start_gsf(self):
        p = os.path.join(REPO, "tests", "data", "input_matrix", "start.GSF")
        if not os.path.exists(p):
            self.skipTest("没有夹具 start.GSF")
        with open(p, "rb") as f:
            info = G.parse_gsf(f.read())
        s = info["state"]
        self.assertEqual((s["camp"], s["next_stage"], s["gold"], list(s["party"]), s["bag"]), (0, 1, 5, ["0"], []))
        self.assertEqual((info["header"]["level"], s["party"]["0"]["lv"]), (5, 5))


class BuildSaveTest(unittest.TestCase):
    def test_save_fields_match_game_format(self):
        raw = make_gsf(party=[HERO])
        mt = datetime.datetime(2026, 10, 1, 8, 5, 9).timestamp()
        save = G.build_save(raw, mt)["save"]
        self.assertEqual(save["where"], "camp")
        self.assertEqual(save["time"], "2026-10-01 08:05:09")   # 源文件修改时间, 不是头里的日期
        self.assertEqual(save["content"], [{"id": "tdj", "version": ""}])
        self.assertNotIn("engine", save)
        self.assertEqual(save["stage"], save["camp"])
        self.assertEqual(base64.b64decode(save["gsf_raw"]), raw)
        # 必需字段齐 (GameState.SAVE_REQUIRED)
        for k in ("stage", "next_stage", "gold", "bag", "game_data", "party"):
            self.assertIn(k, save)
        json.loads(json.dumps(save))

    def test_version_and_fields_in_sync_with_game_code(self):
        if not os.path.exists(os.path.join(REPO, "game", "engine", "core", "save_file.gd")):
            self.skipTest("没有游戏代码 (独立的存档工具仓库)")

        def read(rel):
            with open(os.path.join(REPO, rel), encoding="utf-8") as f:
                return f.read()
        m = re.search(r"const VERSION := (\d+)", read("game/engine/core/save_file.gd"))
        self.assertEqual(G.SAVE_VERSION, int(m.group(1)))
        self.assertIn('"gsf_raw": "str"', read("game/engine/core/game_state.gd"))
        self.assertIn("ENGINE_VERSION", read("game/engine/content/content_compat.gd"))
        mf = os.path.join(REPO, "game", "content", "tdj", "manifest.json")
        if os.path.exists(mf):
            with open(mf, encoding="utf-8") as f:
                self.assertEqual(G.STAGE_LIMIT, json.load(f)["stage_count"])

    def test_gsf_raw_keeps_on_disk_bytes(self):
        raw = make_gsf(party=[HERO])
        save = G.build_save(raw)["save"]
        r = base64.b64decode(save["gsf_raw"])
        self.assertEqual(r[:G.HEADER_SIZE], raw[:G.HEADER_SIZE])
        self.assertEqual(G.xor_body(r[G.HEADER_SIZE:])[8:12], struct.pack("<i", 1234))   # 仍是 XOR 状态, 解开后是金钱


class BadInputTest(unittest.TestCase):
    def test_too_short(self):
        for n in (0, 10, 26, G.GSF_SIZE - 1):
            with self.assertRaises(G.GsfError) as cm:
                G.parse_gsf(b"\0" * n, "x.GSF")
            self.assertIn("太短", str(cm.exception))

    def test_not_a_gsf(self):
        for junk in (b"\0" * G.GSF_SIZE, b"hello world " * 400, bytes(range(256)) * 16):
            with self.assertRaises(G.GsfError):
                G.parse_gsf(junk[:G.GSF_SIZE + 5])

    def test_out_of_range_camp_and_negative_gold(self):
        with self.assertRaises(G.GsfError):
            G.parse_gsf(make_gsf(camp=G.STAGE_LIMIT + 1))
        with self.assertRaises(G.GsfError):
            G.parse_gsf(make_gsf(next_stage=-1))
        with self.assertRaises(G.GsfError):
            G.parse_gsf(make_gsf(gold=-5))

    def test_cli_errors_are_chinese_without_traceback(self):
        with tempfile.TemporaryDirectory() as d:
            short = os.path.join(d, "GD00.GSF")
            with open(short, "wb") as f:
                f.write(b"abc")
            gcf = os.path.join(d, "GAMEDATA.GCF")
            with open(gcf, "wb") as f:
                f.write(make_gsf())
            for path, word in ((os.path.join(d, "nope.GSF"), "找不到"), (short, "太短"), (gcf, "战阵存档"), (os.path.join(d, "emptydir"), "找不到")):
                q = Quiet()
                self.assertEqual(G.main([path, "--out", os.path.join(d, "out")], out=q), 1, path)
                self.assertIn(word, q.text)
                self.assertNotIn("Traceback", q.text)
            os.mkdir(os.path.join(d, "empty"))
            q = Quiet()
            self.assertEqual(G.main([os.path.join(d, "empty")], out=q), 1)
            self.assertIn("GD00.GSF", q.text)
            self.assertFalse(os.path.exists(os.path.join(d, "out")), "失败时不建输出目录")

    def test_unreadable_path_reports(self):
        with tempfile.TemporaryDirectory() as d:
            q = Quiet()
            r = G.import_files([(1, d)], os.path.join(d, "o"), out=q)   # 把目录当文件读
            self.assertEqual(r["failed"], [1])
            self.assertIn("读不了", q.text)


class WriteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.src = os.path.join(self.tmp.name, "src")
        self.out_dir = os.path.join(self.tmp.name, "saves")
        os.mkdir(self.src)

    def gsf(self, name, **kw):
        p = os.path.join(self.src, name)
        with open(p, "wb") as f:
            f.write(make_gsf(party=[HERO], **kw))
        return p

    def load(self, slot):
        with open(os.path.join(self.out_dir, "save%d.json" % slot), encoding="utf-8") as f:
            return json.load(f)

    def test_single_file_by_name_and_by_slot_option(self):
        p = self.gsf("GD02.GSF", gold=11)
        q = Quiet()
        self.assertEqual(G.main([p, "--out", self.out_dir], out=q), 0)
        self.assertEqual(self.load(3)["gold"], 11)   # GD02 -> save3
        self.assertEqual(G.main([p, "--out", self.out_dir, "--slot", "5"], out=q), 0)
        self.assertEqual(self.load(5)["gold"], 11)
        odd = self.gsf("whatever.bin", gold=12)
        self.assertEqual(G.main([odd, "--out", self.out_dir], out=q), 0)   # 名字不规范 -> 槽位 1
        self.assertEqual(self.load(1)["gold"], 12)

    def test_directory_batch_case_insensitive(self):
        self.gsf("GD00.GSF", gold=1)
        self.gsf("gd03.gsf", gold=4)
        self.gsf("GD04.GSF", gold=5)
        self.gsf("GD07.GSF", gold=99)   # 不是营地档位
        q = Quiet()
        self.assertEqual(G.main([self.src, "--out", self.out_dir], out=q), 0)
        self.assertEqual(sorted(os.listdir(self.out_dir)), ["save1.json", "save4.json", "save5.json"])
        self.assertEqual((self.load(1)["gold"], self.load(4)["gold"], self.load(5)["gold"]), (1, 4, 5))
        self.assertIn("读到 3 个", q.text)
        self.assertIn("殷剑平 Lv 7", q.text)
        self.assertIn("前历再续", q.text)

    def test_directory_with_slot_imports_only_that_slot(self):
        self.gsf("GD00.GSF", gold=1)
        self.gsf("GD01.GSF", gold=2)
        self.assertEqual(G.main([self.src, "--out", self.out_dir, "--slot", "2"], out=Quiet()), 0)
        self.assertEqual(os.listdir(self.out_dir), ["save2.json"])
        self.assertEqual(G.main([self.src, "--out", self.out_dir, "--slot", "4"], out=Quiet()), 1)

    def test_dry_run_writes_nothing(self):
        self.gsf("GD00.GSF", gold=1)
        q = Quiet()
        self.assertEqual(G.main([self.src, "--out", self.out_dir, "--dry-run"], out=q), 0)
        self.assertFalse(os.path.exists(self.out_dir), "试运行不建目录")
        self.assertIn("金钱 1 两", q.text)
        self.assertIn("队伍 1 人", q.text)
        self.assertIn("行囊 0 件", q.text)
        self.assertIn("下一关 4", q.text)
        # 目录已存在且有旧档时也不动
        os.makedirs(self.out_dir)
        old = os.path.join(self.out_dir, "save1.json")
        with open(old, "w", encoding="utf-8") as f:
            f.write("OLD")
        G.main([self.src, "--out", self.out_dir, "--dry-run", "--force"], out=Quiet())
        self.assertEqual(os.listdir(self.out_dir), ["save1.json"])
        with open(old, encoding="utf-8") as f:
            self.assertEqual(f.read(), "OLD")

    def test_existing_slot_not_overwritten_without_force(self):
        self.gsf("GD00.GSF", gold=1)
        os.makedirs(self.out_dir)
        old = os.path.join(self.out_dir, "save1.json")
        with open(old, "w", encoding="utf-8") as f:
            f.write("OLD")
        q = Quiet()
        self.assertEqual(G.main([self.src, "--out", self.out_dir], out=q), 3)
        self.assertIn("--force", q.text)
        with open(old, encoding="utf-8") as f:
            self.assertEqual(f.read(), "OLD")
        self.assertEqual(os.listdir(self.out_dir), ["save1.json"], "没有备份、没有临时文件")

    def test_only_bak_counts_as_existing(self):
        # 游戏的 SaveFile.exists: 正式文件缺失但 .bak 在也算有档
        self.gsf("GD00.GSF")
        os.makedirs(self.out_dir)
        with open(os.path.join(self.out_dir, "save1.json.bak"), "w", encoding="utf-8") as f:
            f.write("OLD")
        self.assertEqual(G.main([self.src, "--out", self.out_dir], out=Quiet()), 3)
        self.assertEqual(G.main([self.src, "--out", self.out_dir, "--force"], out=Quiet()), 0)
        baks = [n for n in os.listdir(self.out_dir) if ".bak-" in n]
        self.assertEqual(len(baks), 1)
        with open(os.path.join(self.out_dir, baks[0]), encoding="utf-8") as f:
            self.assertEqual(f.read(), "OLD")

    def test_force_backs_up_old_save_with_timestamp(self):
        self.gsf("GD00.GSF", gold=1)
        os.makedirs(self.out_dir)
        old = os.path.join(self.out_dir, "save1.json")
        with open(old, "w", encoding="utf-8") as f:
            f.write("OLD")
        q = Quiet()
        self.assertEqual(G.main([self.src, "--out", self.out_dir, "--force"], out=q), 0)
        self.assertEqual(self.load(1)["gold"], 1)
        baks = [n for n in os.listdir(self.out_dir) if n.startswith("save1.json.bak-")]
        self.assertEqual(len(baks), 1)
        self.assertRegex(baks[0], r"^save1\.json\.bak-\d{8}-\d{6}$")
        with open(os.path.join(self.out_dir, baks[0]), encoding="utf-8") as f:
            self.assertEqual(f.read(), "OLD")
        self.assertIn("已备份旧档", q.text)
        # 同一秒再覆盖一次: 备份名不撞, 前一份备份不丢
        fixed = datetime.datetime(2026, 1, 2, 3, 4, 5)
        self.assertEqual(G.backup_path(old, fixed), old + ".bak-20260102-030405")
        open(old + ".bak-20260102-030405", "w", encoding="utf-8").close()
        self.assertEqual(G.backup_path(old, fixed), old + ".bak-20260102-030405-2")
        self.assertEqual(G.main([self.src, "--out", self.out_dir, "--force"], out=Quiet()), 0)
        self.assertGreaterEqual(len([n for n in os.listdir(self.out_dir) if ".bak-" in n]), 2)
        self.assertFalse([n for n in os.listdir(self.out_dir) if ".tmp" in n])

    def test_partial_failure_still_writes_good_files(self):
        self.gsf("GD00.GSF", gold=1)
        with open(os.path.join(self.src, "GD01.GSF"), "wb") as f:
            f.write(b"short")
        q = Quiet()
        self.assertEqual(G.main([self.src, "--out", self.out_dir], out=q), 1)
        self.assertEqual(os.listdir(self.out_dir), ["save1.json"])
        self.assertIn("失败", q.text)

    def test_output_is_valid_json_with_utf8_keys(self):
        p = self.gsf("GD00.GSF")
        G.main([p, "--out", self.out_dir], out=Quiet())
        d = self.load(1)
        self.assertEqual(list(d["party"]["0"]["spirit"]), ["迅", "烈", "神", "魔", "魂"])
        self.assertEqual(d["version"], G.SAVE_VERSION)


class DefaultDirTest(unittest.TestCase):
    def test_per_platform(self):
        self.assertTrue(G.default_out_dir("win32", {"APPDATA": r"C:\Users\a\AppData\Roaming"}).endswith("SwordmanHD"))
        self.assertIn("Application Support", G.default_out_dir("darwin", {}))
        self.assertEqual(G.default_out_dir("linux", {"XDG_DATA_HOME": "/x/share"}), os.path.join("/x/share", "SwordmanHD"))
        self.assertTrue(G.default_out_dir("linux", {}).endswith(os.path.join(".local", "share", "SwordmanHD")))

    def test_slot_names(self):
        self.assertEqual([G.slot_of_name(n) for n in ("GD00.GSF", "gd04.gsf", "GD05.GSF", "GAMEDATA.GCF", "GD0.GSF")], [1, 5, None, None, None])


if __name__ == "__main__":
    unittest.main()
