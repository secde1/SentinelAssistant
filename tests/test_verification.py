"""Result Verification: model "SUCCESS" desa ham, faktlar tasdiqlamasa — kod holatni tushiradi."""
import pytest

from agent.verification import Facts, apply, claimed_status, decide

OK = Facts(mutated=False, verified=False, verify_failed=False, run_code="ok")
CHANGED_VERIFIED = Facts(mutated=True, verified=True, verify_failed=False, run_code="ok")
CHANGED_UNVERIFIED = Facts(mutated=True, verified=False, verify_failed=False, run_code="ok")
CHANGED_VERIFY_FAILED = Facts(mutated=True, verified=False, verify_failed=True, run_code="ok")


@pytest.mark.parametrize("text,expected", [
    ("Holat: SUCCESS\nMuammo: x", "SUCCESS"),
    ("✅ Holat: partial — izoh", "PARTIAL"),
    ("Ҳолат: NEEDS_AUTH\nМуаммо: 401", "NEEDS_AUTH"),
    ("Status: BLOCKED", "BLOCKED"),
    ("Holat: OK", None),
    ("Muammo: holat haqida gap yo'q", None),
])
def test_claimed_status(text, expected):
    assert claimed_status(text) == expected


@pytest.mark.parametrize("claimed,facts,expected", [
    ("SUCCESS", CHANGED_VERIFIED, ("SUCCESS", None)),
    (None, CHANGED_VERIFIED, ("SUCCESS", None)),
    ("SUCCESS", CHANGED_UNVERIFIED, ("PARTIAL", "o'zgarishdan keyin qayta o'lchanmadi")),
    ("SUCCESS", CHANGED_VERIFY_FAILED, ("FAILED", "o'zgarishdan keyingi tekshiruv (verify) o'tmadi")),
    ("NEEDS_AUTH", CHANGED_UNVERIFIED, ("NEEDS_AUTH", None)),
    ("SUCCESS", Facts(False, False, False, "limit"), ("PARTIAL", "qadam yoki vaqt chegarasi tugadi")),
    ("SUCCESS", Facts(False, False, False, "refusal"), ("BLOCKED", "model so'rovni rad etdi")),
    (None, Facts(False, False, False, "error"), ("FAILED", "ichki xato")),
    ("SUCCESS", OK, ("SUCCESS", None)),
    (None, OK, (None, None)),
])
def test_decide(claimed, facts, expected):
    assert decide(claimed, facts) == expected


def test_success_without_verify_is_downgraded():
    text, status = apply("Holat: SUCCESS\nMuammo: Spooler\nHozir: tasdiqlandi", CHANGED_UNVERIFIED)
    assert status == "PARTIAL"
    assert text.startswith("⚠️ Holat: PARTIAL — o'zgarishdan keyin qayta o'lchanmadi (kod tekshiruvi)")
    assert text.count("Holat:") == 1
    assert "tasdiqlanmagan (verify yo'q)" in text


def test_verified_success_kept():
    text, status = apply("Holat: SUCCESS\nHozir: Running (verify PASS)", CHANGED_VERIFIED)
    assert status == "SUCCESS" and text.startswith("✅ Holat: SUCCESS\n") and "(kod tekshiruvi)" not in text


def test_no_status_no_facts_unchanged():
    text, status = apply("Xat tayyor, fayl yuborildi.", OK)
    assert status is None and text == "Xat tayyor, fayl yuborildi."


def test_status_added_when_missing():
    text, status = apply("Muammo: disk", CHANGED_UNVERIFIED)
    assert status == "PARTIAL" and text.splitlines()[0].startswith("⚠️ Holat: PARTIAL")
