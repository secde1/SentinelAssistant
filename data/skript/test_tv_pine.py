import copy, hashlib, os, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tv_pine as T

LEGACY_FILE = os.path.join(T.HOME, "ish", "trading", "btc_short.pine")


def sc(**kw):
    s = copy.deepcopy(T.LEGACY_BTC)
    s.update(kw)
    return s


class Generation(unittest.TestCase):
    def test_original_levels_preserved(self):
        code = T.generate_pine(sc())
        for p in ("77500.0", "76600.0", "75250.0", "74400.0"):
            self.assertIn(f"hline({p},", code)
        self.assertTrue(code.startswith("//@version=5"))

    def test_annotation_count(self):
        code = T.generate_pine(sc())
        v = T.validate_pine(code, sc())
        self.assertTrue(v["ok"], v["errors"])
        self.assertEqual(v["hline_count"], 4)  # entry+sl+2tp
        s3 = sc(tp=[75250, 74400, 73500])
        self.assertEqual(T.validate_pine(T.generate_pine(s3), s3)["hline_count"], 5)

    def test_metadata_and_simulation_label(self):
        code = T.generate_pine(sc())
        for need in (T.DISCLAIMER, "BTC-SHORT-20261106-01", "Manual-Research v0", "2026-11-06T15:25:00+05:00",
                     "INVALID:", 'EXPECT_TICKER = "BTCUSDT"', 'EXPECT_TF = "60"'):
            self.assertIn(need, code)

    def test_validator_catches_problems(self):
        s = sc()
        good = T.generate_pine(s)
        bad = {
            "version": good.replace("@version=5", "@version=4"),
            "strategy": good + "strategy.entry('x', strategy.short)\n",
            "paren": good.replace("overlay=true)", "overlay=true"),
            "missing_line": good.replace('hline(74400.0, "SIM TP2 74400", color=color.green, linewidth=2, linestyle=hline.style_solid)\n', ""),
            "no_disclaimer": good.replace(T.DISCLAIMER, "x"),
            "tab": good.replace("    table.cell(info, 0, 0", "\ttable.cell(info, 0, 0", 1),
            "wrong_price": good.replace("hline(76600.0", "hline(76601.0"),
        }
        for name, code in bad.items():
            self.assertFalse(T.validate_pine(code, s)["ok"], name)

    def test_duplicate_hline_detected(self):
        s = sc()
        good = T.generate_pine(s)
        line = [l for l in good.split("\n") if l.startswith("hline(76600.0")][0]
        dup = good.replace(line, line + "\n" + line)
        r = T.validate_pine(dup, s)
        self.assertFalse(r["ok"])
        self.assertTrue(any("duplicate" in e or "hline soni" in e for e in r["errors"]))

    def test_bad_numeric_inputs(self):
        for kw in ({"entry": -1}, {"sl": 76000}, {"tp": [77000, 74400]}, {"tp": []}, {"entry": float("nan")},
                   {"timeframe": "7x"}, {"symbol": "btc usdt"}, {"invalidation": 'has "quote"'}, {"side": "FLAT"}):
            with self.assertRaises(ValueError, msg=str(kw)):
                T.generate_pine(sc(**kw))

    def test_long_ordering(self):
        s = sc(side="LONG", entry=100, sl=95, tp=[105, 110])
        self.assertTrue(T.validate_pine(T.generate_pine(s), s)["ok"])
        with self.assertRaises(ValueError):
            T.generate_pine(sc(side="LONG"))  # SHORT darajalari LONG sifatida


class Instrument(unittest.TestCase):
    def items(self, s, symbol_line="Bitcoin / TetherUS · 1h · BINANCE BTCUSDT", match="Chart matches scenario"):
        rows = [(symbol_line, 0.05), (T.DISCLAIMER, 0.01), ("ID " + s["id"], 0.01)]
        rows += [(t, 0.01) for _, t, _ in T.levels(s)]
        rows.append((match, 0.01))
        return rows

    def test_confirmed_when_all_visible(self):
        s = sc()
        r = T.evaluate_ocr(self.items(s), s, hint="TetherUS")
        self.assertTrue(r["confirmed"], r["missing"])

    def test_wrong_timeframe_detected(self):
        s = sc()
        r = T.evaluate_ocr(self.items(s, "Bitcoin / TetherUS · 4h · BINANCE BTCUSDT", match="WRONG CHART: expected BTCUSDT 60"), s, hint="TetherUS")
        self.assertFalse(r["timeframe"])
        self.assertTrue(r["wrong_chart_shown"])
        self.assertFalse(r["confirmed"])

    def test_wrong_symbol_detected(self):
        s = sc()
        r = T.evaluate_ocr(self.items(s, "Ethereum / TetherUS · 1h · BINANCE ETHUSDT"), s)
        self.assertFalse(r["symbol"])
        self.assertIn("symbol", r["missing"])

    def test_missing_annotation_reported(self):
        s = sc()
        items = [i for i in self.items(s) if "TP2" not in i[0]]
        r = T.evaluate_ocr(items, s, hint="TetherUS")
        self.assertIn("SIM TP2 74400", r["missing"])
        self.assertFalse(r["confirmed"])

    def test_window_title_alone_is_not_confirmation(self):
        s = sc()
        r = T.evaluate_ocr([("BTCUSDT 76216,36 +0.17% / Unnamed", 0.1)], s)
        self.assertFalse(r["confirmed"])

    def test_legend_alone_not_enough(self):
        s = sc()
        items = [i for i in self.items(s) if "matches" not in i[0]]
        r = T.evaluate_ocr(items, s, hint="TetherUS")
        self.assertTrue(r["timeframe_legend_supporting"])
        self.assertFalse(r["confirmed"])

    def test_timeframe_codes(self):
        self.assertEqual(T.timeframe_code("1h"), "60")
        self.assertEqual(T.timeframe_code("4H"), "240")
        self.assertEqual(T.timeframe_code("1d"), "D")


class Status(unittest.TestCase):
    def test_status_table(self):
        self.assertEqual(T.task_status(False, False, "confirmed"), "FAILED")
        self.assertEqual(T.task_status(True, True, "unverified"), "PARTIAL")
        self.assertEqual(T.task_status(True, True, "integration_missing"), "PARTIAL")
        self.assertEqual(T.task_status(True, False, "integration_missing"), "NEEDS_SETUP")
        self.assertEqual(T.task_status(True, True, "confirmed"), "SUCCESS")

    def test_prepare_never_success(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(T.prepare(sc(), pine_dir=d)["status"], "PARTIAL")

    def test_missing_integration_wrong_device(self):
        r = T.verify_chart(sc(), "NB-XS-TEX02-NOT-THIS-PC")
        self.assertEqual(r["state"], "integration_missing")
        self.assertEqual(T.task_status(True, True, r["state"]), "PARTIAL")

    def test_price_check_flags_far_levels(self):
        r = T.check_price(sc(), fetch=lambda _: 50000)
        self.assertFalse(r["ok"])
        r = T.check_price(sc(), fetch=lambda _: 76200)
        self.assertTrue(r["ok"])

        def boom(_):
            raise RuntimeError("net")
        self.assertFalse(T.check_price(sc(), fetch=boom)["checked"])


class Storage(unittest.TestCase):
    def test_duplicate_scenario_saved_once(self):
        with tempfile.TemporaryDirectory() as d:
            a = T.prepare(sc(), pine_dir=d)
            b = T.prepare(sc(id="OTHER-ID-2"), pine_dir=d)  # xuddi shu darajalar
            self.assertEqual(a["save"]["status"], "saved")
            self.assertEqual(b["save"]["status"], "duplicate")
            self.assertEqual(len([f for f in os.listdir(d) if f.endswith(".pine")]), 1)

    def test_existing_file_not_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            s = sc()
            path = os.path.join(d, f"BTCUSDT_60_{s['id']}.pine")
            open(path, "w").write("KEEP")
            with self.assertRaises(FileExistsError):
                T.save_pine(s, T.generate_pine(s), d)
            self.assertEqual(open(path).read(), "KEEP")

    def test_legacy_file_untouched(self):
        if not os.path.exists(LEGACY_FILE):
            self.skipTest("legacy yo'q")
        before = hashlib.sha1(open(LEGACY_FILE, "rb").read()).hexdigest()
        with tempfile.TemporaryDirectory() as d:
            T.prepare(sc(), pine_dir=d)
        self.assertEqual(hashlib.sha1(open(LEGACY_FILE, "rb").read()).hexdigest(), before)


if __name__ == "__main__":
    unittest.main(verbosity=1)
