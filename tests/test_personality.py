"""shaxsiyat.json -> prompt ko'rsatmalari: darajalar, chegaralash, bayroqlar, buzuq fayl."""
import json

import pytest

from agent.personality import band, level, render


def write(tmp_path, data):
    p = tmp_path / "shaxsiyat.json"
    p.write_text(json.dumps(data, ensure_ascii=False) if not isinstance(data, str) else data, encoding="utf-8")
    return p


@pytest.mark.parametrize("value,expected", [(0, 0), (20, 0), (21, 1), (60, 2), (80, 3), (85, 4), (100, 4)])
def test_band(value, expected):
    assert band(value) == expected


def test_level_clamps_and_defaults():
    assert level(150, "x") == 100 and level(-5, "x") == 0 and level("abc", "x") == 50 and level("70", "x") == 70


def test_owner_settings(tmp_path):
    p = write(tmp_path, {"agent": "SENTINAL AI", "personality": {
        "emotional_expressiveness": 100, "humor_level": 100, "independent_opinions": 85,
        "owner_style_adaptation": 100, "allow_constructive_disagreement": True, "allow_contextual_frustration": True}})
    text = render(p)
    assert "Isming: SENTINAL AI" in text
    assert "Hazil: 100/100 (maksimal) — hazil — xarakteringning asosiy qismi" in text
    assert "Mustaqil fikr: 85/100 (maksimal)" in text
    assert "Konstruktiv e'tiroz: ruxsat" in text and "Vaziyatga mos norozilik: ruxsat" in text
    assert "uchinchi shaxsga yuboriladigan xabarda — muloyim, hazilsiz" in text  # cheklov har doim bor


def test_low_and_disabled(tmp_path):
    text = render(write(tmp_path, {"personality": {"humor_level": 10, "allow_contextual_frustration": False}}))
    assert "Hazil: 10/100 (juda past) — hazil yo'q" in text
    assert "Vaziyatga mos norozilik: yo'q — har doim xotirjam ohang" in text
    assert "Isming" not in text and "Hissiyot ifodasi" not in text


@pytest.mark.parametrize("content", ["{buzuq json", json.dumps({"agent": "X"}), json.dumps({"personality": [1, 2]})])
def test_broken_file_falls_back(tmp_path, content):
    assert render(write(tmp_path, content)) == ""


def test_missing_file(tmp_path):
    assert render(tmp_path / "yoq.json") == ""
