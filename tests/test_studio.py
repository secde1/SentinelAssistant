"""Reels studiyasi: skript qoidalari, kirill->lotin, holatlar mashinasi, versiyaga bog'langan tasdiq, yordamchilar."""
import copy
from datetime import datetime

import pytest

from agent.studio import pipeline, render
from agent.studio.script import split_sentences, to_latin, validate
from agent.studio.store import StudioStore, TransitionError
from agent.verification import claimed_status

GOOD = {
    "topic": "Telefonga qaramlik", "title": "Телефон ва болалар", "category": "raqamli-qaramlik",
    "scenes": [
        {"role": "hook", "screen": "Болангиз кунига неча соат телефонда?", "narration": "Болангиз кунига неча соат телефонда ўтиради?"},
        {"role": "problem", "screen": "Экран вақти ортиб бормоқда", "narration": "Кўпчилик оилаларда экран вақти назоратсиз."},
        {"role": "solution", "screen": "Оилавий қоидалар", "narration": "Биргаликда оддий қоидалар белгиланг."},
        {"role": "ending", "screen": "Сиз қандай қоида қўйгансиз?", "narration": "Изоҳларда ёзинг: сиз қандай қоида қўйгансиз?"},
    ],
    "caption": "Экран вақти ҳақида гаплашайлик.", "hashtags": ["#оила", "#болалар"],
    "sources": [{"title": "WHO", "url": "https://www.who.int/"}],
}


@pytest.mark.parametrize("cyr,lat", [
    ("Ўзбекистон", "O'zbekiston"), ("Ер", "Yer"), ("мева", "meva"), ("шаҳар", "shahar"), ("ғоя", "g'oya"),
    ("Қизиқ", "Qiziq"), ("Юлдуз", "Yulduz"), ("ёшлар", "yoshlar"), ("Ёшлар", "Yoshlar"), ("оилае", "oilaye"),
    ("Нега? Чунки!", "Nega? Chunki!"),
])
def test_to_latin(cyr, lat):
    assert to_latin(cyr) == lat


def test_split_sentences():
    parts = split_sentences("Биринчи гап. Иккинчи гап! " + "сўз, " * 40 + "охир.")
    assert parts[0] == "Биринчи гап." and parts[1] == "Иккинчи гап!"
    assert all(len(p) <= 110 for p in parts)


def test_good_script_passes():
    assert validate(GOOD) == []


@pytest.mark.parametrize("mutate,needle", [
    (lambda s: s["scenes"][1].update(narration="Ko'pchilik oilalarda ekran vaqti nazoratsiz."), "KIRILL"),
    (lambda s: s.update(sources=[]), "sources"),
    (lambda s: s["scenes"].reverse(), "hook"),
    (lambda s: s.update(hashtags=["#t"] * 31), "hashtags"),
    (lambda s: s.update(scenes=s["scenes"][:2]), "4-8"),
    (lambda s: s["scenes"][0].update(screen="Я" * 200), "screen"),
])
def test_bad_scripts(mutate, needle):
    s = copy.deepcopy(GOOD)
    mutate(s)
    assert any(needle in e for e in validate(s))


def test_state_machine_and_versioned_approval(tmp_path):
    store = StudioStore(tmp_path)
    rid = store.create("t", "c", "T")
    assert rid.endswith("-01") and store.new_id().endswith("-02")
    with pytest.raises(TransitionError):
        store.transition(rid, "APPROVED", "egasi")  # IDEA -> APPROVED mumkin emas
    v = store.start_version(rid, GOOD)
    for st in ("SCRIPT_READY", "VIDEO_RENDERING", "QUALITY_CHECK"):
        store.transition(rid, st, "kod")
    video = tmp_path / "v.mp4"
    video.write_bytes(b"video-1")
    store.finish_version(rid, v, video, 40.0, "edge")
    store.transition(rid, "PENDING_APPROVAL", "kod")
    with pytest.raises(TransitionError):
        store.approve(rid, v + 1)  # boshqa versiya
    video.write_bytes(b"o'zgargan")
    with pytest.raises(TransitionError, match="o'zgargan"):
        store.approve(rid, v)  # fayl tasdiqqa yuborilgandan keyin o'zgargan
    video.write_bytes(b"video-1")
    digest = store.approve(rid, v)
    reel = store.get(rid)
    assert reel["state"] == "APPROVED" and reel["approved_version"] == v and reel["approved_sha256"] == digest
    assert [e["to_state"] for e in store.events(rid)][-1] == "APPROVED"
    assert store.count_today() == 1


def test_settings(tmp_path):
    store = StudioStore(tmp_path)
    assert store.setting("paused", "0") == "0"
    store.set_setting("paused", "1")
    assert store.setting("paused") == "1"


def test_parse_when():
    now = datetime(2026, 10, 31, 20, 0)
    assert pipeline.parse_when("19:30", now) == datetime(2026, 11, 1, 19, 30)
    assert pipeline.parse_when("21:15", now) == datetime(2026, 10, 31, 21, 15)
    assert pipeline.parse_when("эртага 09:00", now) == datetime(2026, 11, 1, 9, 0)
    assert pipeline.parse_when("01.11 19:30", now) == datetime(2026, 11, 1, 19, 30)
    assert pipeline.parse_when("30.10 10:00", now) is None and pipeline.parse_when("кечқурун", now) is None


def test_buttons_and_slot():
    kb = pipeline.buttons("R1031-01", 3)
    datas = [b["callback_data"] for row in kb["inline_keyboard"] for b in row]
    assert datas[0] == "rl:R1031-01:3:ok" and all(len(d.encode()) <= 64 for d in datas)
    assert pipeline.suggest_slot("R1031-01") in pipeline.EXPERIMENT_SLOTS


def test_scene_timeline():
    from agent.studio.tts import Clip
    clips = [Clip(0, "a", 0.35, 2.0), Clip(1, "b", 2.5, 4.0), Clip(1, "c", 4.2, 5.0), Clip(2, "d", 5.5, 7.0),
             Clip(3, "e", 7.5, 9.0)]
    scenes = pipeline.scene_timeline(GOOD, clips, 10.0)
    assert scenes[0].start == 0 and scenes[1].start == pytest.approx(2.3) and scenes[-1].end == 10.0
    assert [s.text for s in scenes[1].subs] == ["b", "c"]


def test_font_has_uzbek_letters():
    assert render.missing_glyphs(render.find_font(), "ЎўҚқҒғҲҳ") == ""


def test_v5_status_alias():
    assert claimed_status("Holat: NEEDS_AUTHORIZATION") == "NEEDS_AUTH"
