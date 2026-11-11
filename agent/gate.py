"""Xavfsizlik-gate: har tool chaqiruvini KOD darajasida tasniflaydi (promptga ishonilmaydi).

Darajalar:
  read     — faqat o'qish
  internal — agentning o'z fayllari (xotira/skill/ish/zaxira)
  change   — o'zgartiradi, lekin so'ramay bajariladi (restart, log tozalash, parol tiklash...)
  danger   — Jamshid tasdig'i kerak; javob yoki timeout bo'lmasa — BAJARILMAYDI
  block    — umuman bajarilmaydi (maxfiy papkaga to'g'ridan-to'g'ri murojaat va h.k.)

Gate atayin ehtiyotkor: shubhali holatda danger qaytaradi.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from .inventory import has_placeholders

READ, INTERNAL, CHANGE, DANGER, BLOCK = "read", "internal", "change", "danger", "block"
_ORDER = {READ: 0, INTERNAL: 1, CHANGE: 2, DANGER: 3, BLOCK: 4}

# Bu toifadagi amalni tasdiqqa yuborishdan oldin shu hostdan zaxira olingan bo'lishi SHART.
BACKUP_REQUIRED = {"network_config", "policy"}

_F = re.I | re.M


@dataclass
class Decision:
    level: str = READ
    reasons: list[str] = field(default_factory=list)
    categories: set[str] = field(default_factory=set)
    host: str = "localhost"

    def escalate(self, level: str, reason: str | None = None, category: str | None = None) -> "Decision":
        if _ORDER[level] > _ORDER[self.level]:
            self.level = level
        if reason and reason not in self.reasons:
            self.reasons.append(reason)
        if category:
            self.categories.add(category)
        return self

    @property
    def needs_approval(self) -> bool:
        return self.level == DANGER

    @property
    def mutating(self) -> bool:
        return self.level in (CHANGE, DANGER)

    @property
    def needs_backup(self) -> bool:
        return self.level == DANGER and bool(self.categories & BACKUP_REQUIRED)


def _rx(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, _F)


# ---------------------------------------------------------------- PowerShell
_PS_DANGER: list[tuple[re.Pattern[str], str, str]] = [(_rx(p), c, r) for p, c, r in [
    (r"\bSendKeys\b|\bSendWait\b|\bkeybd_event\b|\bmouse_event\b|\bSendInput\b|\bSetCursorPos\b|\bpyautogui\b"
     r"|\bpynput\b|\bAutoHotkey\b|\bInvokePattern\b|\bValuePattern\b|\bLegacyIAccessiblePattern\b",
     "gui_input", "Kor-korona GUI kiritish (klaviatura/sichqoncha simulyatsiyasi): oyna holatini ko'rmasdan bosish "
                  "boshqa oynani yopishi yoki noto'g'ri amal bajarishi mumkin"),
    (r"\b(?:Restart|Stop)-Computer\b", "power", "Server qayta yuklanadi yoki o'chadi"),
    (r"\bshutdown(?:\.exe)?\s+(?:[/-]\w+\s+)*?[/-](?:r|s|p|g|h|hybrid)\b", "power", "shutdown buyrug'i"),
    (r"\b(?:Stop|Restart|Suspend|Save|Remove|Reset)-VM\b", "power", "VM o'chiriladi / qayta yuklanadi"),
    (r"\b(?:Remove|Restore)-VM(?:Snapshot|Checkpoint)\b|\bRemove-Snapshot\b|\bSet-VM\b[^|;\n]*-Snapshot\b",
     "data_loss", "Snapshot o'chiriladi yoki qaytariladi"),
    (r"\b(?:Stop|Restart|Shutdown)-VMGuest\b|\b(?:Stop|Restart|Suspend|Remove)-VMHost\b"
     r"|\bRemove-(?:HardDisk|Datastore|VMHardDiskDrive)\b", "power", "ESXi/Hyper-V xost yoki disk amali"),
    (r"\b(?:Stop-Process|taskkill)\b[^|;\n]*\b(?:lsass|csrss|wininit|winlogon|services|smss)\b",
     "power", "Tizim jarayoni o'ldiriladi (server yiqiladi)"),
    (r"\b(?:Remove-Item|rm|ri|del|erase|rd|rmdir)\b[^|;\n]*?\s-r[a-z]*\b", "data_loss",
     "Remove-Item -Recurse (papka butunlay o'chadi)"),
    (r"\b(?:rd|rmdir|del|erase)\b[^|;\n]*\s/s\b", "data_loss", "rd/del /s (rekursiv o'chirish)"),
    (r"\bshutil\.rmtree\b|\bos\.removedirs\b", "data_loss", "Python orqali rekursiv o'chirish"),
    (r"\bFormat-Volume\b|\bformat(?:\.com)?\s+[a-z]:", "data_loss", "Disk formatlanadi"),
    (r"\b(?:Clear-Disk|Initialize-Disk|Remove-Partition|New-Partition|Resize-Partition|Set-Partition|Set-Disk"
     r"|Remove-PhysicalDisk|Remove-StoragePool|Remove-VirtualDisk)\b|\bdiskpart\b", "data_loss", "Disk/partition o'zgaradi"),
    (r"\bvssadmin\b[^|;\n]*\bdelete\b|\bwbadmin\b[^|;\n]*\bdelete\b", "data_loss", "Shadow copy / backup o'chiriladi"),
    (r"\bDROP\s+(?:DATABASE|TABLE|SCHEMA|LOGIN|USER)\b|\bTRUNCATE\s+TABLE\b", "data_loss", "DB drop/truncate"),
    (r"\bDELETE\s+FROM\s+[\w.\[\]]+(?![^;'\"]*\bWHERE\b)", "data_loss", "WHERE'siz DELETE (butun jadval)"),
    (r"\bRemove-(?:ADUser|ADComputer|ADGroup|ADObject|ADOrganizationalUnit|LocalUser|Mailbox)\b",
     "data_loss", "AD/lokal obyekt o'chiriladi"),
    (r"\breg(?:\.exe)?\s+delete\b|\bRemove-Item\b[^|;\n]*\bHK(?:LM|CU|CR|U|CC):", "data_loss", "Registr kaliti o'chiriladi"),
    (r"\b(?:New|Remove|Set|Import|Restore|Rename|Copy)-GPO\b|\b(?:New|Remove|Set)-GPLink\b"
     r"|\b(?:Set|Remove)-GP(?:Registry|Prf|Permission|Inheritance)\w*\b", "policy", "GPO o'zgaradi"),
    (r"\b(?:New|Set|Rename)-ADOrganizationalUnit\b|\bMove-ADObject\b", "policy", "OU o'zgaradi"),
    (r"\bSet-AD(?:Domain|Forest|DomainMode|ForestMode|DefaultDomainPasswordPolicy|FineGrainedPasswordPolicy"
     r"|ReplicationSite\w*)\b|\bNew-ADFineGrainedPasswordPolicy\b", "policy", "Domen darajasidagi siyosat"),
    (r"\b(?:Add|Set|Remove|Restore|Import|Rename|Invoke)-DhcpServer(?!v[46]Lease|v[46]Reservation)\w*\b|\bnetsh\s+dhcp\b",
     "policy", "DHCP server sozlamasi"),
    (r"\bRemove-DhcpServerv[46]Lease\b(?![^|;\n]*-(?:IPAddress|ClientId))", "policy", "Scope'dagi barcha lease o'chiriladi"),
    (r"\b(?:Add|Set|Remove|Restore|Import|Register|Unregister|Resume|Suspend|Sync|Reset|Start|Stop)-DnsServer"
     r"(?!ResourceRecord)\w*\b|\bdnscmd\b[^|;\n]*/(?:zonedelete|zoneadd|config|resetforwarders|zoneresetsecondaries)",
     "policy", "DNS server sozlamasi"),
    (r"\b(?:New|Set|Remove|Enable|Disable|Copy|Rename)-NetFirewall\w*\b"
     r"|\bnetsh\s+(?:advfirewall|firewall)\s+(?:\S+\s+)*?(?:set|add|delete|reset|import)\b", "policy", "Firewall o'zgaradi"),
    (r"\bSet-MpPreference\b[^|;\n]*-Disable\w*\s+\$?(?:true|1)\b|\bAdd-MpPreference\b[^|;\n]*-Exclusion",
     "policy", "Antivirus himoyasi kamaytiriladi"),
    (r"\bAdd-(?:ADGroupMember|LocalGroupMember)\b[^|;\n]*\b(?:Domain Admins|Enterprise Admins|Schema Admins|Administrators"
     r"|Account Operators|Backup Operators|Server Operators)\b"
     r"|\bnet\s+(?:local)?group\s+['\"]?(?:Domain Admins|Enterprise Admins|Administrators)['\"]?\s+\S+\s+/add\b",
     "policy", "Imtiyozli guruhga a'zo qo'shiladi"),
    (r"\b(?:Set-DnsClientServerAddress|New-NetIPAddress|Remove-NetIPAddress|Set-NetIPAddress|Set-NetIPInterface"
     r"|Disable-NetAdapter|Restart-NetAdapter|Remove-NetRoute|New-NetRoute|Set-NetAdapter\w*)\b"
     r"|\bnetsh\s+interface\s+(?:ip|ipv4|ipv6)\s+(?:set|add|delete)\b|\broute(?:\.exe)?\s+(?:delete|add|change)\b",
     "network_config", "Server tarmoq sozlamasi (aloqa uzilishi mumkin)"),
    (r"\bSet-Service\b[^|;\n]*-StartupType\s+['\"]?Disabled\b"
     r"|\bsc(?:\.exe)?\s+(?:\\\\\S+\s+)?config\s+\S+\s+start\s*=\s*disabled\b"
     r"|\bsc(?:\.exe)?\s+(?:\\\\\S+\s+)?delete\b|\bRemove-Service\b", "service_disable", "Xizmat butunlay o'chiriladi"),
    (r"\s-e(?:c|nc|ncodedcommand)?\s+[A-Za-z0-9+/=]{20,}|\bInvoke-Expression\b|\biex\b|\[ScriptBlock\]::Create\b",
     "obfuscated", "Yashirin/dinamik buyruq — gate mazmunini tekshira olmaydi"),
]]

_PS_STOP = _rx(r"\bStop-Service\b|\bspsv\b|\bnet\s+stop\b|\bsc(?:\.exe)?\s+(?:\\\\\S+\s+)?stop\b")
_PS_START = _rx(r"\bStart-Service\b|\bsasv\b|\bRestart-Service\b|\bnet\s+start\b|\bsc(?:\.exe)?\s+(?:\\\\\S+\s+)?start\b")
_PS_AD_BULK_SRC = _rx(r"\b(?:Get|Search)-AD\w+\b[^|\n]*(?:-Filter|-LDAPFilter|-SearchBase)\b|\bSearch-ADAccount\b")
_PS_AD_BULK_DST = _rx(r"\b(?:Set|Disable|Enable|Remove|Move|Add|Clear|Rename)-AD\w+\b|\bSet-ADAccountPassword\b")
_PS_GCI_REMOVE = _rx(r"\b(?:Get-ChildItem|gci|dir|ls)\b[^|;\n]*\s-r[a-z]*\b[^;\n]*\|\s*(?:Remove-Item|rm|ri|del)\b")
_PS_GCI_FILTERED = _rx(r"-Filter\b|-Include\b|-Exclude\b|Where-Object|\bwhere\b|\?\s*\{|LastWriteTime|CreationTime")
_PS_EGRESS = _rx(r"\b(?:Invoke-WebRequest|Invoke-RestMethod|iwr|irm|curl|wget|Start-BitsTransfer|Send-MailMessage"
                 r"|Net\.WebClient|HttpClient|ftp|scp|sftp)\b")

_MUTATING_VERBS = {
    "set", "new", "remove", "add", "clear", "restart", "start", "stop", "enable", "disable", "install",
    "uninstall", "update", "reset", "unlock", "move", "rename", "copy", "register", "unregister", "import",
    "initialize", "mount", "dismount", "suspend", "resume", "grant", "revoke", "restore", "repair",
    "lock", "block", "unblock", "protect", "unprotect", "publish", "unpublish", "approve", "deny", "undo",
    "optimize", "sync", "merge", "split", "join", "edit", "expand", "compress", "backup", "checkpoint",
    "save", "submit", "send", "invoke", "rebuild", "reboot",
}
_NEUTRAL_CMDLETS = {c.lower() for c in (
    "New-Object", "New-TimeSpan", "New-PSSession", "Remove-PSSession", "New-CimSession", "Remove-CimSession",
    "New-CimSessionOption", "New-PSSessionOption", "New-ScheduledTaskTrigger", "New-ScheduledTaskAction",
    "New-ScheduledTaskPrincipal", "New-ScheduledTaskSettingsSet", "New-Guid", "New-Variable", "Set-Variable",
    "Remove-Variable", "Clear-Variable", "Set-Location", "Set-StrictMode", "Add-Type", "Add-Member",
    "Import-Module", "Import-Csv", "Import-Clixml", "Import-PowerShellDataFile", "Start-Sleep", "Start-Transcript",
    "Stop-Transcript", "Invoke-Command", "Invoke-WebRequest", "Invoke-RestMethod", "Invoke-Sqlcmd", "Join-Path",
    "Split-Path", "Clear-Host", "Start-Job", "Stop-Job", "Remove-Job", "Start-ThreadJob", "Connect-VIServer",
    "Disconnect-VIServer", "Set-PSReadLineOption", "Set-ExecutionPolicy", "Remove-Module", "Send-Ping",
    "Join-String", "Update-TypeData", "Update-FormatData",
)}
_CMDLET_RE = _rx(r"(?<![\w-])([a-z]+)-([a-z][a-z0-9]+)\b")
_PS_NATIVE_CHANGE = _rx(
    r"\bnet\s+(?:stop|start|user|localgroup|group|use|share|session)\b"
    r"|\bsc(?:\.exe)?\s+(?:\\\\\S+\s+)?(?:start|stop|config|create|failure|pause|continue)\b"
    r"|\breg(?:\.exe)?\s+(?:add|import|copy|restore|load|unload)\b|\bnetsh\b[^|;\n]*\b(?:set|add|delete|reset)\b"
    r"|\bipconfig\s+/(?:flushdns|release|renew|registerdns)\b|\bicacls\b[^|;\n]*/(?:grant|remove|deny|reset|setowner|inheritance)"
    r"|\btakeown\b|\brobocopy\b|\bxcopy\b|\bschtasks\b[^|;\n]*/(?:create|delete|change|run|end)\b"
    r"|\b(?:winget|choco)\s+(?:install|uninstall|upgrade)\b|\bmsiexec\b|\bdism\b[^|;\n]*/(?:enable|disable|add|remove|cleanup|restorehealth)"
    r"|\bsfc\s+/scannow\b|\bbcdedit\b[^|;\n]*/(?:set|delete|create|default)\b|\bw32tm\s+/(?:resync|config|register)\b"
    r"|\bgpupdate\b|\bklist\s+purge\b|\bcertutil\b[^|;\n]*-(?:delstore|addstore|importpfx|repairstore)\b"
    r"|\bwmic\b[^|;\n]*\b(?:call|delete|set|create)\b|\btaskkill\b|\blogoff\b|\brwinsta\b|\breset\s+session\b"
    r"|\btsdiscon\b|\bpip\s+install\b|\bwevtutil\s+(?:cl|clear-log)\b|\bprintui\b|\bprn\w+\.vbs\b"
    r"|\b(?:UPDATE\s+\S+\s+SET|INSERT\s+INTO|DELETE\s+FROM|ALTER\s+(?:TABLE|DATABASE)|CREATE\s+(?:TABLE|DATABASE|INDEX))\b"
    r"|-Method\s+['\"]?(?:Post|Put|Patch|Delete)\b"
)
_SCRIPT_REF = _rx(r"[\"']((?:[a-z]:\\|\\\\)[^\"'\n]+\.(?:ps1|psm1|bat|cmd|py|vbs))[\"']"
                  r"|((?:[a-z]:\\|\.{1,2}\\|\\\\)[^\s'\"|;&]+\.(?:ps1|psm1|bat|cmd|py|vbs))")


def referenced_scripts(command: str, base_dir: Path | None = None) -> list[str]:
    """Buyruq ichida chaqirilgan lokal skript fayllarining matni (gate ularni ham tekshiradi)."""
    texts: list[str] = []
    for m in _SCRIPT_REF.finditer(command or ""):
        raw = m.group(1) or m.group(2)
        p = Path(raw)
        if not p.is_absolute() and base_dir is not None:
            p = base_dir / raw
        try:
            if p.is_file() and p.stat().st_size < 2_000_000:
                texts.append(p.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            continue
    return texts


# Login/kalit saqlanadigan joylar: brauzer parollari va cookie, SSH kalitlari, Claude va bulut CLI loginlari, Windows
# Credential Manager/DPAPI, parol menejeri bazalari. Shaxsiy fayllar bilan ishlaganda ham o'qilmaydi va yozilmaydi.
_CREDENTIAL_STORES = re.compile(
    r"[\\/]\.(?:ssh|claude|aws|azure|kube|gnupg|docker)(?:[\\/\"'\s]|$)|\.credentials\.json\b"
    r"|[\\/](?:Login Data|Cookies|Web Data|Local State|key[34]\.db|logins\.json|cookies\.sqlite)(?:[\\/\"'\s]|$)"
    r"|[\\/]Microsoft[\\/](?:Credentials|Protect|Vault)(?:[\\/\"'\s]|$)|\.kdbx\b|\bid_(?:rsa|ed25519|ecdsa|dsa)\b",
    re.I)
_CREDENTIAL_REASON = ("login/kalit saqlanadigan joyga murojaat taqiqlangan (brauzer parollari va cookie, .ssh, Claude "
                      "logini, Windows Credential Manager, parol menejeri)")


# Real savdo: SENTINAL faqat tadqiqot va qog'oz savdo. Buyurtma API'lari faqat egasining tasdig'i bilan (DANGER); agentning o'zida buyurtma kodi yo'q.
_TRADE_ORDER = _rx(r"\border_send\b|\bOrderSend(?:Async)?\s*\(|\bTRADE_ACTION_(?:DEAL|PENDING|SLTP|MODIFY|REMOVE|CLOSE_BY)\b"
                   r"|\bCTrade\b|\bPosition(?:Close|Modify)\s*\(|\bcreate_(?:market_|limit_)?(?:buy_|sell_)?order\b"
                   r"|\bnew_order\b|\border_(?:market|limit)_(?:buy|sell)\b|\bfutures_create_order\b|\bplace_order\b")
_TRADE_REASON = ("Real savdo buyrug'i (order): broker yoki birjaga haqiqiy buyurtma yuboradi — faqat egasining tasdig'i bilan")
# MT5: initialize() yopiq terminalni o'zi ishga tushiradi; Exness terminali REAL hisobda — faqat egasining tasdig'i bilan.
_MT5_DIRECT = _rx(r"\bimport\s+MetaTrader5\b|\bfrom\s+MetaTrader5\s+import\b|\bStart-Process\b[^|;\n]*terminal64"
                  r"|&\s*['\"]?[^'\"\n|;]*terminal64\.exe")
_MT5_REASON = ("MT5 terminaliga to'g'ridan-to'g'ri murojaat: initialize() yopiq terminalni o'zi ishga tushiradi (Exness "
               "terminali REAL hisobda). MT5 bilan ishlash bu agentning vazifasi emas (alohida SENTINEL Trading loyihasi)")


def trading_risk(text: str) -> tuple[str, str, str] | None:
    """Skript yoki buyruq matnidagi savdo xavfi: (daraja, sabab, kategoriya) yoki None."""
    if _TRADE_ORDER.search(text or ""):
        return DANGER, _TRADE_REASON, "real_trade"
    if _MT5_DIRECT.search(text or ""):
        return DANGER, _MT5_REASON, "broker_terminal"
    return None


def credential_store_ref(text: str) -> bool:
    return bool(_CREDENTIAL_STORES.search(text or ""))


def secret_path_refs(text: str, protected: list[Path]) -> list[str]:
    low = (text or "").lower().replace("/", "\\")
    hits = []
    for p in protected:
        s = str(p).lower().replace("/", "\\")
        if s and s in low:
            hits.append(str(p))
    if re.search(r"(?:^|[\\\s'\"=])\.env\b", text or "", re.I | re.M):
        hits.append(".env")
    return hits


def _ps_mutating(text: str) -> bool:
    for m in _CMDLET_RE.finditer(text):
        verb, noun = m.group(1).lower(), m.group(2).lower()
        if verb in _MUTATING_VERBS and f"{verb}-{noun}" not in _NEUTRAL_CMDLETS:
            return True
    return bool(_PS_NATIVE_CHANGE.search(text))


def classify_powershell(command: str, host: str = "localhost", extra_texts: list[str] | None = None,
                        protected_paths: list[Path] | None = None) -> Decision:
    d = Decision(host=host or "localhost")
    text = "\n".join([command or ""] + list(extra_texts or []))
    refs = secret_path_refs(text, protected_paths or [])
    if refs:
        return d.escalate(BLOCK, "maxfiy fayl/papkaga to'g'ridan-to'g'ri murojaat taqiqlangan — placeholder ishlating",
                          "secret_access")
    if credential_store_ref(text):
        return d.escalate(BLOCK, _CREDENTIAL_REASON, "secret_access")
    risk = trading_risk(text)
    if risk:
        d.escalate(*risk)
    for rx, cat, reason in _PS_DANGER:
        if rx.search(text):
            d.escalate(DANGER, reason, cat)
    if _PS_STOP.search(text) and not _PS_START.search(text):
        d.escalate(DANGER, "Xizmat to'xtatiladi va qayta yoqilmaydi (qayta ishga tushirish uchun Restart-Service)",
                   "service_disable")
    if _PS_AD_BULK_SRC.search(text) and _PS_AD_BULK_DST.search(text):
        d.escalate(DANGER, "Ko'p AD obyektiga ommaviy o'zgartirish", "policy")
    if _PS_GCI_REMOVE.search(text) and not _PS_GCI_FILTERED.search(text):
        d.escalate(DANGER, "Papkadagi hamma narsa filtrsiz o'chiriladi", "data_loss")
    if has_placeholders(text) and _PS_EGRESS.search(text):
        d.escalate(DANGER, "Maxfiy qiymat tarmoq buyrug'i orqali yuborilmoqda", "secret_egress")
    if d.level == READ and _ps_mutating(text):
        d.escalate(CHANGE, "o'zgartiruvchi buyruq")
    return d


# ---------------------------------------------------------------- SSH qurilmalar
_ROS_WRITE = {
    "add", "set", "remove", "enable", "disable", "move", "unset", "edit", "import", "reset", "reset-configuration",
    "reboot", "shutdown", "upgrade", "install", "downgrade", "uninstall", "comment", "apply", "make-static",
    "release", "renew", "run", "load", "check-installation",
}
_ROS_CHANGE = {"save", "flush", "reset-counters", "reset-counters-all"}
_ROS_KV = re.compile(r"\b[\w-]+=(?:\"[^\"]*\"|[^\s\[{]\S*)")

_NETOS_READ_FIRST = {
    "show", "sh", "display", "dis", "ping", "traceroute", "tracert", "more", "dir", "who", "whoami",
    "enable", "exit", "quit", "end", "terminal", "term", "screen-length", "history",
}

_UNIFI_READ_FIRST = {
    "info", "cat", "ls", "ps", "top", "ifconfig", "iwconfig", "iwlist", "logread", "dmesg", "uptime", "ping",
    "traceroute", "mca-dump", "uname", "free", "df", "netstat", "arp", "brctl", "grep", "tail", "head", "echo",
}
_UNIFI_CHANGE_FIRST = {"set-inform"}

_LINUX_DANGER: list[tuple[re.Pattern[str], str, str]] = [(_rx(p), c, r) for p, c, r in [
    (r"\brm\s+(?:-[a-z]*r[a-z]*|--recursive)\b", "data_loss", "rm -r (rekursiv o'chirish)"),
    (r"\bmkfs(?:\.\w+)?\b|\bwipefs\b|\b(?:fdisk|sfdisk|gdisk|parted)\b|\b(?:pvremove|vgremove|lvremove)\b"
     r"|\bdd\b[^|;\n]*\bof=/dev/", "data_loss", "Disk/partition o'zgaradi"),
    (r"(?:^|[;&|]\s*|\bsudo\s+)(?:shutdown|reboot|poweroff|halt)\b|\bsystemctl\s+(?:poweroff|reboot|halt|kexec)\b"
     r"|\binit\s+[06]\b", "power", "Qayta yuklash/o'chirish"),
    (r"\bsystemctl\s+(?:stop|disable|mask)\b|\bservice\s+\S+\s+stop\b|\bupdate-rc\.d\s+\S+\s+(?:disable|remove)\b",
     "service_disable", "Xizmat to'xtatiladi/o'chiriladi"),
    (r"\biptables\b[^|;\n]*\s(?:-F|--flush|-X|-D|--delete|-P\s+\w+\s+DROP)\b|\bnft\s+(?:flush|delete)\b"
     r"|\bufw\s+(?:disable|reset|delete|deny)\b|\bfirewall-cmd\b[^|;\n]*--(?:remove|set-default-zone|panic-on)",
     "policy", "Firewall o'zgaradi"),
    (r"\b(?:userdel|deluser|groupdel)\b", "data_loss", "Foydalanuvchi o'chiriladi"),
    (r"\bDROP\s+(?:DATABASE|TABLE|SCHEMA)\b|\bTRUNCATE\s+TABLE\b", "data_loss", "DB drop/truncate"),
    (r"\bdocker\s+(?:rm|rmi|system\s+prune|volume\s+(?:rm|prune)|stop|kill)\b|\bkubectl\s+delete\b"
     r"|\bvirsh\s+(?:destroy|undefine|shutdown|reboot|snapshot-delete)\b", "data_loss", "Konteyner/VM o'chiriladi"),
    (r"\bvim-cmd\s+vmsvc/(?:power\.(?:off|reset|shutdown|reboot|suspend)|destroy|unregister"
     r"|snapshot\.(?:remove|removeall|revert))\b", "power", "ESXi VM amali"),
    (r"\besxcli\b[^|;\n]*\b(?:system\s+shutdown|system\s+maintenanceMode\s+set|network\s+firewall\s+(?:set|unload)"
     r"|storage\b[^|;\n]*\b(?:remove|unmount|detach))\b", "power", "ESXi xost amali"),
    (r"\bcrontab\s+-r\b|\b(?:chmod|chown)\s+-R\b|>\s*/dev/sd[a-z]|\b(?:ip|ifconfig)\b[^|;\n]*\b(?:down|del|delete|flush)\b",
     "data_loss", "Keng ta'sirli amal"),
    (r"\b(?:set-default|restore-default|syswrapper\.sh)\b", "network_config", "Qurilma zavod sozlamasiga qaytariladi"),
]]
_LINUX_CHANGE = _rx(
    r"\bsystemctl\s+(?:restart|start|reload|enable)\b|\bservice\s+\S+\s+(?:restart|start|reload)\b"
    r"|\b(?:apt|apt-get|yum|dnf)\s+(?:install|upgrade|update|remove|purge)\b|\b(?:cp|mv|mkdir|touch|tee|ln|kill|pkill|killall"
    r"|useradd|usermod|passwd|chpasswd|chmod|chown|truncate|logrotate)\b|\bsed\s+-i\b|\becho\b[^|;\n]*>"
    r"|\bdocker\s+(?:restart|start|run|pull)\b|\besxcli\b[^|;\n]*\bset\b|\bvim-cmd\s+vmsvc/power\.on\b|\bset-inform\b"
)

_LINUX_LIKE = {"linux", "unifi", "esxi"}


def _classify_routeros(cmd: str, d: Decision) -> None:
    stripped = _ROS_KV.sub(" ", cmd.lower())
    tokens = {t for t in re.split(r"[\s/;\[\]{}]+", stripped) if t}
    write = tokens & _ROS_WRITE
    if write:
        d.escalate(DANGER, f"Mikrotik konfiguratsiyasiga yozish ({', '.join(sorted(write))})", "network_config")
    elif "fetch" in tokens and re.search(r"upload\s*=\s*yes", cmd, re.I):
        d.escalate(DANGER, "Routerdan fayl tashqariga yuklanadi", "network_config")
    elif tokens & _ROS_CHANGE or "fetch" in tokens or ("export" in tokens and "file=" in cmd.lower()):
        d.escalate(CHANGE, "Mikrotik: zaxira/kesh amali")


def _classify_netos(cmd: str, d: Decision) -> None:
    low = cmd.strip().lower()
    first = low.split()[0] if low.split() else ""
    if re.match(r"copy\s+(?:running-config|run)\s+(?:tftp|scp|ftp|sftp|flash:)", low) and "start" not in low:
        d.escalate(CHANGE, "Konfiguratsiya zaxirasi")
    elif first in _NETOS_READ_FIRST:
        return
    else:
        d.escalate(DANGER, f"Tarmoq uskunasiga konfiguratsiya yozish: '{cmd.strip()[:60]}'", "network_config")


def _classify_unifi(cmd: str, d: Decision) -> None:
    low = cmd.strip().lower()
    parts = low.split()
    first = parts[0] if parts else ""
    if first == "mca-cli-op" and len(parts) > 1:
        first = parts[1]
    for rx, cat, reason in _LINUX_DANGER:
        if rx.search(low):
            d.escalate(DANGER, reason, cat)
            return
    if first in _UNIFI_CHANGE_FIRST:
        d.escalate(CHANGE, "UniFi: controllerga ulash (set-inform)")
    elif first == "swctrl" and "show" in parts:
        return
    elif first == "ip" and not ({"add", "del", "delete", "flush", "change", "replace", "set"} & set(parts)):
        return
    elif first not in _UNIFI_READ_FIRST or ">" in low:
        d.escalate(DANGER, f"UniFi qurilmasida o'zgartiruvchi buyruq: '{cmd.strip()[:60]}'", "network_config")


def classify_ssh(device_type: str, commands: list[str], host: str) -> Decision:
    d = Decision(host=host)
    dt = (device_type or "linux").lower()
    for cmd in commands:
        if not cmd.strip():
            continue
        if dt == "mikrotik_routeros":
            _classify_routeros(cmd, d)
        elif dt == "unifi":
            _classify_unifi(cmd, d)
        elif dt in _LINUX_LIKE:
            for rx, cat, reason in _LINUX_DANGER:
                if rx.search(cmd):
                    d.escalate(DANGER, reason, cat)
            if d.level == READ and _LINUX_CHANGE.search(cmd):
                d.escalate(CHANGE, "o'zgartiruvchi buyruq")
        else:
            _classify_netos(cmd, d)
    return d


# ---------------------------------------------------------------- HTTP API
_AUTH_PATH = _rx(r"/(?:api/)?(?:auth/)?log(?:in|out)\b|/api/session\b|/rest/com/vmware/cis/session\b"
                 r"|/api/auth\b|/oauth2?/token\b|/session(?:s)?/?$")
_DANGER_WORDS = _rx(r"reboot|restart|shutdown|reset|factory|format|delete|remove|destroy|drop|purge|wipe|power|upgrade|firmware")
_UNIFI_CHANGE_CMDS = {"adopt", "set-locate", "unset-locate", "speedtest", "speedtest-status", "power-cycle",
                      "kick-sta", "block-sta", "unblock-sta", "backup", "list-backups"}


def classify_http(method: str, url: str, body_text: str = "", system: str = "other", host: str = "") -> Decision:
    m = (method or "GET").upper()
    parsed = urlparse(url or "")
    path = (parsed.path or "/").lower()
    d = Decision(host=host or (parsed.hostname or ""))
    sysname = (system or "other").lower()
    if m in ("GET", "HEAD", "OPTIONS"):
        return d
    if m == "DELETE":
        return d.escalate(DANGER, "HTTP DELETE (ma'lumot o'chiriladi)", "data_loss")
    if _AUTH_PATH.search(path):
        return d
    body = {}
    try:
        body = json.loads(body_text) if body_text else {}
    except ValueError:
        body = {}

    if sysname == "zabbix":
        zm = str(body.get("method", "")).lower() if isinstance(body, dict) else ""
        if zm.endswith(".get") or zm in {"user.login", "user.logout", "apiinfo.version", "user.checkauthentication"}:
            return d
        if zm.endswith(".delete") or "massremove" in zm:
            return d.escalate(DANGER, f"Zabbix: {zm} (o'chirish)", "data_loss")
        return d.escalate(CHANGE, f"Zabbix: {zm or 'yozish'}")

    if sysname == "unifi":
        if "/stat/" in path or path.rstrip("/").endswith("/stat"):
            return d
        if "/cmd/devmgr" in path or "/cmd/stamgr" in path or "/cmd/backup" in path:
            cmd = str(body.get("cmd", "")).lower() if isinstance(body, dict) else ""
            if cmd in _UNIFI_CHANGE_CMDS:
                return d.escalate(CHANGE, f"UniFi: {cmd}")
            return d.escalate(DANGER, f"UniFi qurilma buyrug'i: {cmd or '?'}", "network_config")
        return d.escalate(DANGER, "UniFi konfiguratsiyasiga yozish", "network_config")

    if sysname == "mikrotik":
        if re.search(r"/(?:print|monitor|monitor-traffic|ping)/?$", path):
            return d
        return d.escalate(DANGER, "Mikrotik REST orqali konfiguratsiyaga yozish", "network_config")

    if sysname == "esxi":
        hay = path + " " + (parsed.query or "").lower() + " " + (body_text or "").lower()
        if "power" in hay or "snapshot" in hay or _DANGER_WORDS.search(hay):
            return d.escalate(DANGER, "ESXi/vCenter: VM quvvati yoki snapshot amali", "power")
        return d.escalate(DANGER, "ESXi/vCenter konfiguratsiyasiga yozish", "policy")

    hay = path + " " + (parsed.query or "").lower() + " " + (body_text or "").lower()[:4000]
    if _DANGER_WORDS.search(hay):
        return d.escalate(DANGER, f"{sysname.upper()}: xavfli amal (reboot/delete/format...)", "data_loss")
    return d.escalate(CHANGE, f"HTTP {m}")


# ---------------------------------------------------------------- fayllar
def _norm(p: Path) -> list[str]:
    forms = [os.path.normcase(os.path.abspath(p))]
    try:
        forms.append(os.path.normcase(str(Path(p).resolve())))
    except OSError:
        pass
    return forms


def inside(path: Path, root: Path) -> bool:
    """path root ichidami (yoki o'zimi). Katta-kichik harf, '..' va junction/symlink hisobga olinadi."""
    roots = [r.rstrip("\\/") for r in _norm(root)]
    for p in _norm(path):
        for r in roots:
            if p == r or p.startswith(r + os.sep):
                return True
    return False


def classify_file_write(path: Path, agent_home: Path, secret_paths: list[Path], code_root: Path | None = None) -> Decision:
    d = Decision(host="localhost")
    for p in secret_paths:
        if inside(path, p):
            return d.escalate(BLOCK, f"{p} ga yozish taqiqlangan (maxfiy ma'lumot faqat request_credentials orqali)",
                              "secret_access")
    if credential_store_ref(str(path)):
        return d.escalate(BLOCK, _CREDENTIAL_REASON, "secret_access")
    if inside(path, agent_home):
        return d.escalate(INTERNAL)
    if code_root is not None and inside(path, code_root):
        return d.escalate(BLOCK, "Agent kodi va SYSTEM_PROMPT.md o'zgartirilmaydi — qo'shimchani "
                                 "xotira/prompt_qoshimcha.md ga yozing", "code")
    return d.escalate(CHANGE, "agent papkasidan tashqaridagi fayl o'zgaradi (avtomatik zaxira olinadi)")


def classify_file_read(path: Path, protected: list[Path]) -> Decision:
    d = Decision(host="localhost")
    for p in protected:
        if inside(path, p):
            return d.escalate(BLOCK, "maxfiy fayllarni o'qish taqiqlangan — list_inventory ishlating", "secret_access")
    if credential_store_ref(str(path)):
        return d.escalate(BLOCK, _CREDENTIAL_REASON, "secret_access")
    return d
