"""MT5 simvol kategoriyasi: brokerning HAQIQIY yo'lidan ('Standard\\Forex\\EURUSDm'); nom o'ylab topilmaydi (faqat metall prefiksi)."""
from __future__ import annotations

METALS = ("XAU", "XAG", "XPT", "XPD")
GROUPS = {"Forex": "Forex", "Stocks": "Stocks", "Crypto": "Crypto", "CryptoCross": "Crypto", "Indices": "Indices", "Idx_Enlarge": "Indices",
          "Energies": "Commodities", "Forex_Indicator": "Indicators"}


def mt5_category(name: str, path: str) -> str:
    group = (path or "").split("\\")[-2] if path and "\\" in path else ""
    if any(name.upper().startswith(m) for m in METALS):
        return "Metals"
    return GROUPS.get(group, group or "Other")


def mt5_groups(connector) -> dict[str, str]:
    """{simvol: kategoriya} — MT5 symbols_get (faqat o'qish)."""
    return {i.name: mt5_category(i.name, getattr(i, "path", "") or "") for i in (connector.mt5.symbols_get() or [])}
