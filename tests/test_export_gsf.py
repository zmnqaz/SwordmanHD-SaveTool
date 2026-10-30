# SPDX-License-Identifier: GPL-3.0-only
"""tools/saves/export_gsf.py (复刻 saveN.json -> 原版 GDxx.GSF)、save_ops.py (转一个存档文件、放进游戏存档位; 存档工具界面背后的逻辑)。
夹具 GSF 在仓库 tests/data/input_matrix 里 (没有就跳过); 其余现场合成, 不入库二进制。"""
import base64
import datetime
import glob
import json
import os
import struct
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
REPO = os.path.dirname(TOOLS)
sys.path.insert(0, os.path.join(TOOLS, "saves"))
sys.path.insert(0, os.path.join(TOOLS, "savetool"))   # 独立的 SwordmanHD-SaveTool 仓库里源码在这里
sys.path.insert(0, HERE)
import export_gsf as X  # noqa: E402
import import_gsf as G  # noqa: E402
import save_ops as O  # noqa: E402
import test_import_gsf as TI  # noqa: E402

FIXTURES = sorted(glob.glob(os.path.join(REPO, "tests", "data", "input_matrix", "*.GSF")) +
                  glob.glob(os.path.join(REPO, "docs", "机制规格", "实测记录", "*.GSF")))
NOW = datetime.datetime(2026, 10, 30, 9, 8, 7)


def read(path):
    with open(path, "rb") as f:
        return f.read()


def write(path, data):
    with open(path, "wb" if isinstance(data, bytes) else "w", **({} if isinstance(data, bytes) else {"encoding": "utf-8"})) as f:
        f.write(data)


def jread(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_of(raw, mtime=0):
    """GSF 字节 -> 复刻版存档字典 (和 JSON 读回来一样: 数都可能是 float)。"""
    return json.loads(json.dumps(G.build_save(raw, mtime)["save"]))


def party_save(**over):
    s = {"stage": 5, "next_stage": 6, "camp": 5, "gold": 100, "bag": [1, 2, 3], "game_data": {"3": 7}, "seeded": [0],
         "party": {"0": {"lv": 9.0, "exp": 10.0, "hp_max": 99.0, "mp_max": 30.0, "stats": {"str": 11.0, "int": 12.0, "avg": 13.0, "vit": 14.0, "luk": 15.0},
                         "gear": {"weapon": 4.0, "armor": None, "accessory": 7.0}, "skills": [0.0, 5.0], "spirit": {"迅": 1.0, "烈": 2.0, "神": 3.0, "魔": 4.0, "魂": 5.0},
                         "spirit_points": 2, "items": [4.0, 7.0]}},
         "where": "camp", "time": "2026-10-04 15:27:00", "content": [{"id": "tdj", "version": "1.3.0"}], "version": 2}
    s.update(over)
    return s


class Quiet:
    def __init__(self):
        self.lines = []

    def __call__(self, s=""):
        self.lines.append(str(s))

    @property
    def text(self):
        return "\n".join(self.lines)


class RoundTripTest(unittest.TestCase):
    def test_fixtures_exact_with_gsf_raw_base(self):
        if not FIXTURES:
            self.skipTest("没有夹具 GSF")
        for p in FIXTURES:
            with self.subTest(os.path.basename(p)):
                raw = read(p)
                out, info = X.build_gsf(save_of(raw))
                self.assertEqual(out[:8] + out[26:], raw[:8] + raw[26:])   # 头里的日期时间换成存档时间, 其余逐字节相同
                self.assertEqual(info["base"], "存档里保留的原版字节 gsf_raw")

    def test_fixtures_parse_equal_with_template_base(self):
        if not FIXTURES:
            self.skipTest("没有夹具 GSF")
        for p in FIXTURES:
            with self.subTest(os.path.basename(p)):
                raw = read(p)
                s = save_of(raw)
                s.pop("gsf_raw")
                out, info = X.build_gsf(s)
                self.assertEqual(info["base"], "内置模板")
                self.assertEqual(G.parse_gsf(out)["state"], G.parse_gsf(raw)["state"])
                self.assertEqual(G.parse_header(out)["camp_no"], G.parse_header(raw)["camp_no"])

    def test_template_reproduces_new_game_start(self):
        p = os.path.join(REPO, "tests", "data", "input_matrix", "start.GSF")
        if not os.path.exists(p):
            self.skipTest("没有夹具 start.GSF")
        raw = read(p)
        s = save_of(raw)
        s.pop("gsf_raw")
        out, _ = X.build_gsf(s)
        self.assertEqual(out[:8] + out[26:], raw[:8] + raw[26:])   # 内置模板 + 开局存档内容 = 原版开局存档

    def test_template_is_valid_gsf(self):
        t = X.template_gsf()
        self.assertEqual(len(t), G.GSF_SIZE)
        self.assertEqual(G.parse_gsf(t)["state"]["party"], {})


class BuildTest(unittest.TestCase):
    def test_fields_and_header(self):
        out, info = X.build_gsf(party_save())
        r = G.parse_gsf(out)
        s = r["state"]
        self.assertEqual((s["camp"], s["next_stage"], s["gold"], s["bag"], s["game_data"]), (5, 6, 100, [1, 2, 3], {"3": 7}))
        self.assertEqual(s["party"]["0"]["gear"], {"weapon": 4, "armor": None, "accessory": 7})
        self.assertEqual(s["party"]["0"]["skills"], [0, 5])
        self.assertEqual((r["header"]["level"], r["header"]["date"], r["header"]["time"]), (9, "10/04/26", "15:27:00"))
        self.assertEqual(info["warnings"], [])

    def test_header_time_falls_back_to_now(self):
        out, _ = X.build_gsf(party_save(time="乱写"), now=NOW)
        h = G.parse_header(out)
        self.assertEqual((h["date"], h["time"]), ("10/30/26", "09:08:07"))

    def test_base_unknown_bytes_kept_and_camp_copies_follow(self):
        base = TI.make_gsf(camp=22, next_stage=24, party=[TI.HERO])
        d = bytearray(G.xor_body(base[G.HEADER_SIZE:]))
        struct.pack_into("<iiiii", d, 4, 51, 6, 23, 22, 22)   # +04 +08(金钱) +0C +10 +14 (+10/+14 与头里的进度值 22 相等)
        struct.pack_into("<i", d, 0x18, 257)
        d[0xF1C:0xF20] = b"\x10\x20\x30\x40"
        base = base[:G.HEADER_SIZE] + G.xor_body(bytes(d))
        out, info = X.build_gsf(party_save(), base_raw=base)
        b = G.xor_body(out[G.HEADER_SIZE:])
        self.assertEqual(struct.unpack_from("<iii", b, 4)[0:1] + struct.unpack_from("<i", b, 0xC), (51, 23))
        self.assertEqual(struct.unpack_from("<ii", b, 0x10), (5, 5))   # 副本跟着新进度值 5
        self.assertEqual(struct.unpack_from("<i", b, 0x18)[0], 257)
        self.assertEqual(b[0xF1C:0xF20], b"\x10\x20\x30\x40")
        self.assertEqual(info["base"], "指定的原版存档")

    def test_camp_copies_not_touched_when_base_differs(self):
        out, _ = X.build_gsf(party_save())   # 模板: +0x10 = -1, +0x14 = 0, 头里进度值 0: +0x14 == 0 会跟着走, +0x10 不跟
        b = G.xor_body(out[G.HEADER_SIZE:])
        self.assertEqual(struct.unpack_from("<i", b, 0x10)[0], -1)

    def test_new_member_goes_to_first_empty_record_and_departed_keeps_bytes(self):
        base = TI.make_gsf(party=[dict(TI.HERO, rec=0), dict(rec=1, uid=4, lv=20, exp=77), dict(rec=2, uid=6, lv=30, on=0)])
        s = party_save()
        s["party"]["9"] = {"lv": 3, "hp_max": 40, "mp_max": 10}
        s.pop("gsf_raw", None)
        out, _ = X.build_gsf(s, base_raw=base)
        b = G.xor_body(out[G.HEADER_SIZE:])
        rec = lambda r: b[0x21C + 80 * r:0x21C + 80 * (r + 1)]
        self.assertEqual(struct.unpack_from("<hh", rec(1), 0)[0], 4)             # 4 号原来在队, 现在不在队: 标成 0
        self.assertEqual(struct.unpack_from("<h", rec(1), 0x24)[0], 0)
        self.assertEqual(struct.unpack_from("<hhh", rec(1), 0)[2], 77)           # 其余字节保留
        self.assertEqual(struct.unpack_from("<hh", rec(2), 0)[0], 6)             # 6 号原本不在队, 原样保留
        self.assertEqual(struct.unpack_from("<h", rec(3), 0)[0], 9)              # 新成员放进第一个空记录
        self.assertEqual(struct.unpack_from("<h", rec(3), 0x24)[0], 1)
        self.assertEqual(sorted(G.parse_gsf(out)["state"]["party"], key=int), ["0", "9"])

    def test_full_roster_reuses_departed_record_with_warning(self):
        recs = [dict(rec=r, uid=r + 10, lv=2, on=0 if r else 1) for r in range(16)]
        recs[0]["uid"] = 0
        base = TI.make_gsf(party=recs)
        s = party_save()
        s["party"]["99"] = {"lv": 1}
        out, info = X.build_gsf(s, base_raw=base)
        self.assertIn("99", sorted(G.parse_gsf(out)["state"]["party"]))
        self.assertTrue(any("没有空位" in w for w in info["warnings"]))

    def test_extra_items_bag_and_variables_warn(self):
        s = party_save(bag=list(range(600)), game_data={"3": 7, "200": 1, "x": 2})
        s["party"]["0"]["items"] = list(range(12))
        out, info = X.build_gsf(s)
        self.assertEqual(len(G.parse_gsf(out)["state"]["bag"]), 512)
        self.assertEqual(len(info["warnings"]), 3)
        self.assertEqual(G.parse_gsf(out)["state"]["game_data"], {"3": 7})

    def test_foreign_content_pack_warns(self):
        _, info = X.build_gsf(party_save(content=[{"id": "tdj", "version": ""}, {"id": "moonclip", "version": "1"}]))
        self.assertTrue(any("moonclip" in w for w in info["warnings"]))

    def test_errors_are_chinese_gsf_errors(self):
        cases = [
            (party_save(where="battle"), "营地存档"),
            ({k: v for k, v in party_save().items() if k != "bag"}, "bag"),
            (party_save(gold=-5), "合理范围"),
            (party_save(next_stage=99), "合理范围"),
            (party_save(gold="多"), "不是数字"),
            (party_save(party={"0": {"lv": 70000}}), "超出"),
            (party_save(party={"x": {}}), "不是整数"),
            (party_save(gsf_raw="@@@"), "base64"),
            (party_save(gsf_raw=base64.b64encode(b"abc").decode()), "长度"),
            (party_save(party={str(i): {} for i in range(17)}), "16 人"),
        ]
        for save, word in cases:
            with self.subTest(word):
                with self.assertRaises(G.GsfError) as cm:
                    X.build_gsf(save)
                self.assertIn(word, str(cm.exception))

    def test_short_base_rejected(self):
        with self.assertRaises(G.GsfError):
            X.build_gsf(party_save(), base_raw=b"\0" * 100)


class ExportFilesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.src = os.path.join(self.tmp.name, "replica")
        self.dst = os.path.join(self.tmp.name, "orig")
        os.makedirs(self.src)
        for n in (1, 2):
            with open(os.path.join(self.src, "save%d.json" % n), "w", encoding="utf-8") as f:
                json.dump(party_save(gold=100 * n), f)

    def run_export(self, *args):
        q = Quiet()
        code = X.main([self.src, "--out", self.dst] + list(args), out=q)
        return code, q.text

    def test_writes_slots_to_gd_files(self):
        code, text = self.run_export()
        self.assertEqual(code, 0, text)
        self.assertEqual(sorted(os.listdir(self.dst)), ["GD00.GSF", "GD01.GSF"])
        self.assertEqual(G.parse_gsf(read(os.path.join(self.dst, "GD01.GSF")))["state"]["gold"], 200)

    def test_dry_run_writes_nothing(self):
        code, text = self.run_export("--dry-run")
        self.assertEqual(code, 0)
        self.assertFalse(os.path.exists(self.dst))

    def test_existing_skipped_then_force_backs_up(self):
        self.run_export()
        code, text = self.run_export()
        self.assertEqual(code, 3, text)
        self.assertIn("--force", text)
        code, text = self.run_export("--force")
        self.assertEqual(code, 0, text)
        baks = [f for f in os.listdir(self.dst) if ".bak-" in f]
        self.assertEqual(len(baks), 2)

    def test_existing_spelling_kept_case_insensitive(self):
        os.makedirs(self.dst)
        with open(os.path.join(self.dst, "gd00.gsf"), "wb") as f:
            f.write(b"old")
        code, _ = self.run_export("--slot", "1", "--force")
        self.assertEqual(code, 0)
        self.assertIn("gd00.gsf", os.listdir(self.dst))
        self.assertNotIn("GD00.GSF", os.listdir(self.dst))

    def test_slot_option_with_file_and_bad_files(self):
        with open(os.path.join(self.src, "save3.json"), "w", encoding="utf-8") as f:
            f.write("{坏的")
        code, text = self.run_export()
        self.assertEqual(code, 1)          # 有一个读不了
        self.assertIn("不是有效的 JSON", text)
        self.assertTrue(os.path.exists(os.path.join(self.dst, "GD01.GSF")))   # 其余照常导出
        q = Quiet()
        X.main([os.path.join(self.src, "save1.json"), "--out", self.dst, "--slot", "5", "--force"], out=q)
        self.assertTrue(os.path.exists(os.path.join(self.dst, "GD04.GSF")))

    def test_base_option(self):
        base = os.path.join(self.tmp.name, "base.GSF")
        with open(base, "wb") as f:
            f.write(TI.make_gsf(party=[TI.HERO]))
        code, text = self.run_export("--base", base)
        self.assertEqual(code, 0, text)
        self.assertIn("指定的原版存档", text)

    def test_no_saves_in_dir(self):
        q = Quiet()
        self.assertEqual(X.main([self.tmp.name, "--out", self.dst], out=q), 1)
        self.assertIn("没有 save1.json", q.text)

    def test_import_then_export_is_identity_on_game_fields(self):
        orig = os.path.join(self.tmp.name, "game")
        os.makedirs(orig)
        raw = TI.make_gsf(camp=7, next_stage=8, gold=555, game_data={5: 3}, bag=[9, 9, 1], party=[TI.HERO, dict(rec=1, uid=3, lv=4)])
        with open(os.path.join(orig, "GD02.GSF"), "wb") as f:
            f.write(raw)
        rep = os.path.join(self.tmp.name, "rep")
        G.main([orig, "--out", rep], out=Quiet())
        back = os.path.join(self.tmp.name, "back")
        X.main([rep, "--out", back], out=Quiet())
        got = read(os.path.join(back, "GD02.GSF"))
        self.assertEqual(got[:8] + got[26:], raw[:8] + raw[26:])


class ConvertFileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = self.tmp.name

    def gsf(self, name="GD01.GSF", **kw):
        p = os.path.join(self.dir, name)
        with open(p, "wb") as f:
            f.write(TI.make_gsf(party=[TI.HERO], **kw))
        return p

    def json_save(self, name="save2.json", **over):
        p = os.path.join(self.dir, name)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(party_save(**over), f)
        return p

    def test_original_to_replica_goes_beside_source_in_result_folder(self):
        src = self.gsf(gold=77)
        r = O.convert_file(src)
        self.assertEqual((r["direction"], r["kind_out"], r["slot"]), (O.TO_REPLICA, "replica", 2))
        self.assertEqual(r["out_path"], os.path.join(self.dir, O.OUT_FOLDER, "save2.json"))
        self.assertEqual(jread(r["out_path"])["gold"], 77)
        self.assertIn("金钱 77", r["summary"])
        self.assertIn("殷剑平 Lv 7", r["summary"])
        self.assertEqual(read(src), TI.make_gsf(party=[TI.HERO], gold=77))   # 源文件不动

    def test_replica_to_original(self):
        r = O.convert_file(self.json_save(gold=321))
        self.assertEqual((r["direction"], r["kind_out"], r["slot"]), (O.TO_ORIGINAL, "original", 2))
        self.assertEqual(os.path.basename(r["out_path"]), "GD01.GSF")
        self.assertEqual(G.parse_gsf(read(r["out_path"]))["state"]["gold"], 321)
        self.assertIn("金钱 321", r["summary"])

    def test_same_result_reused_different_result_never_overwrites(self):
        src = self.gsf(gold=5)
        a = O.convert_file(src)
        b = O.convert_file(src)
        self.assertEqual(a["out_path"], b["out_path"])      # 再拖一次: 内容一样就沿用, 不堆文件
        src2 = self.gsf(gold=6)
        c = O.convert_file(src2)
        self.assertEqual(os.path.basename(c["out_path"]), "save2 (2).json")   # 内容不同: 不覆盖上一份
        self.assertEqual(jread(a["out_path"])["gold"], 5)

    def test_odd_names_use_slot_one_and_out_dir_option(self):
        p = os.path.join(self.dir, "我的存档.gsf")
        os.replace(self.gsf(), p)
        out = os.path.join(self.dir, "别处")
        r = O.convert_file(p, out_dir=out)
        self.assertEqual((r["slot"], os.path.dirname(r["out_path"])), (1, out))

    def test_errors_are_chinese(self):
        bad = os.path.join(self.dir, "x.txt")
        write(bad, "hi")
        short = os.path.join(self.dir, "GD00.GSF")
        write(short, b"\0" * 10)
        broken = os.path.join(self.dir, "save1.json")
        write(broken, "{坏")
        battle = os.path.join(self.dir, "GAMEDATA.GCF")
        write(battle, b"\0" * 5000)
        for path, word in [(bad, "看不懂"), (short, "太短"), (broken, "JSON"), (battle, "战阵存档"), (os.path.join(self.dir, "没有.GSF"), "读不了")]:
            with self.subTest(word):
                with self.assertRaises(G.GsfError) as cm:
                    O.convert_file(path)
                self.assertIn(word, str(cm.exception))

    def test_expect_rejects_wrong_kind_for_the_page(self):
        g, j = self.gsf(), self.json_save()
        self.assertEqual(O.convert_file(g, expect=O.TO_REPLICA)["direction"], O.TO_REPLICA)
        self.assertEqual(O.convert_file(j, expect=O.TO_ORIGINAL)["direction"], O.TO_ORIGINAL)
        for path, expect, word in [(j, O.TO_REPLICA, "原版存档"), (g, O.TO_ORIGINAL, "复刻版存档")]:
            with self.assertRaises(G.GsfError) as cm:
                O.convert_file(path, expect=expect)
            self.assertIn(word, str(cm.exception))
        self.assertFalse(os.path.exists(os.path.join(self.dir, O.OUT_FOLDER, "GD01.GSF.bak")))

    def test_battle_location_json_rejected(self):
        with self.assertRaises(G.GsfError):
            O.convert_file(self.json_save(where="battle"))


class PlaceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = self.tmp.name
        src = os.path.join(self.dir, "GD02.GSF")
        with open(src, "wb") as f:
            f.write(TI.make_gsf(party=[TI.HERO], gold=900))
        self.to_replica = O.convert_file(src)
        sav = os.path.join(self.dir, "save1.json")
        with open(sav, "w", encoding="utf-8") as f:
            json.dump(party_save(gold=15), f)
        self.to_original = O.convert_file(sav)

    def test_place_into_empty_slot(self):
        game = os.path.join(self.dir, "game")
        r = O.place(self.to_replica, game, 4)
        self.assertEqual((r["dst"], r["backup"]), (os.path.join(game, "save4.json"), None))
        self.assertEqual(jread(r["dst"])["gold"], 900)

    def test_taken_slot_asks_then_overwrites_with_backup(self):
        game = os.path.join(self.dir, "game")
        O.place(self.to_replica, game, 1)
        with self.assertRaises(O.SlotTaken):
            O.place(self.to_replica, game, 1)
        r = O.place(self.to_replica, game, 1, overwrite=True, now=NOW)
        self.assertTrue(r["backup"].endswith(".bak-20261030-090807"))
        self.assertEqual(sorted(os.listdir(game)), ["save1.json", "save1.json.bak-20261030-090807"])

    def test_game_own_bak_counts_as_taken(self):
        game = os.path.join(self.dir, "game")
        os.makedirs(game)
        write(os.path.join(game, "save3.json.bak"), "{}")
        with self.assertRaises(O.SlotTaken):
            O.place(self.to_replica, game, 3)

    def test_place_original_uses_existing_spelling_and_backs_up(self):
        game = os.path.join(self.dir, "orig")
        os.makedirs(game)
        write(os.path.join(game, "gd04.gsf"), b"old")
        with self.assertRaises(O.SlotTaken):
            O.place(self.to_original, game, 5)
        r = O.place(self.to_original, game, 5, overwrite=True, now=NOW)
        self.assertEqual(os.path.basename(r["dst"]), "gd04.gsf")
        self.assertEqual(read(r["backup"]), b"old")
        self.assertEqual(G.parse_gsf(read(r["dst"]))["state"]["gold"], 15)

    def test_any_slot_works_regardless_of_source_slot(self):
        game = os.path.join(self.dir, "game")
        O.place(self.to_original, game, 3)
        self.assertEqual(os.listdir(game), ["GD02.GSF"])

    def test_config_remember_and_game_dir(self):
        cfg = os.path.join(self.dir, "cfg.json")
        self.assertEqual(O.load_config(cfg), {})
        self.assertIsNone(O.game_dir("original", {}))
        O.remember("original_dir", self.dir, cfg)
        d = O.load_config(cfg)
        self.assertEqual(O.game_dir("original", d), self.dir)
        self.assertIsNone(O.game_dir("original", {"original_dir": os.path.join(self.dir, "没有")}))   # 记过的目录没了就重新问
        self.assertEqual(O.game_dir("replica", d), G.default_out_dir())
        write(cfg, "坏")
        self.assertEqual(O.load_config(cfg), {})


if __name__ == "__main__":
    unittest.main()
