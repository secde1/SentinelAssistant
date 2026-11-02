#Requires -RunAsAdministrator
<#
.SYNOPSIS
  IT-agentni Windows serverga o'rnatadi.

.DESCRIPTION
  1) .env ni tayyorlaydi (yo'q bo'lsa .env.example dan) va unga faqat SYSTEM + Administrators huquq beradi
  2) .venv bo'lmasa Python 3.11+ ni topadi/o'rnatadi va .venv yaratadi; requirements.txt ni o'rnatadi
     (claude-agent-sdk rasmiy Claude Code CLI'ni olib keladi)
  3) PowerShell 7 (pwsh) ni o'rnatadi (bo'lmasa)
  4) AGENT_HOME papkalarini yaratadi (xotira, skill, jurnal, maxfiy, zaxira, ish, skript) va u yerda .gitignore yozadi;
     maxfiy\ ga faqat SYSTEM + Administrators huquq
  5) NSSM orqali Windows xizmatini yaratadi (avtomatik start, yiqilsa qayta ko'tariladi)
  6) Haftalik xulosa uchun Task Scheduler vazifasini yaratadi
  Kalitlar (.env) to'ldirilmagan bo'lsa — xizmat yaratiladi, lekin ishga tushirilmaydi.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\install.ps1
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\install.ps1 -AgentHome D:\it-agent\data -WeeklyDay Friday -WeeklyTime 17:00
#>
[CmdletBinding()]
param(
    [string]$AgentHome = "",
    [string]$ServiceName = "ITAgent",
    [string]$PythonExe = "",
    [switch]$SkipPwsh,
    [switch]$SkipService,
    [switch]$SkipWeeklyTask,
    [ValidateSet("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")]
    [string]$WeeklyDay = "Monday",
    [string]$WeeklyTime = "09:00"
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$ProjectDir = $PSScriptRoot
$EnvFile = Join-Path $ProjectDir '.env'
$PythonUrl = 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe'
$PwshMsiUrl = 'https://github.com/PowerShell/PowerShell/releases/download/v7.4.6/PowerShell-7.4.6-win-x64.msi'
$NssmZipUrl = 'https://nssm.cc/release/nssm-2.24.zip'
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)

function Write-Step([string]$t) { Write-Host "`n==> $t" -ForegroundColor Cyan }
function Write-Ok([string]$t) { Write-Host "  [OK] $t" -ForegroundColor Green }
function Write-Note([string]$t) { Write-Host "  [!] $t" -ForegroundColor Yellow }

function Get-EnvValue([string]$Name) {
    if (-not (Test-Path $EnvFile)) { return "" }
    foreach ($line in [System.IO.File]::ReadAllLines($EnvFile)) {
        if ($line -match "^\s*$Name\s*=\s*(.*)$") { return $Matches[1].Trim().Trim('"').Trim("'") }
    }
    return ""
}

function Set-EnvValue([string]$Name, [string]$Value) {
    $lines = [System.Collections.Generic.List[string]]::new()
    $found = $false
    foreach ($line in [System.IO.File]::ReadAllLines($EnvFile)) {
        if ($line -match "^\s*$Name\s*=") { $lines.Add("$Name=$Value"); $found = $true } else { $lines.Add($line) }
    }
    if (-not $found) { $lines.Add("$Name=$Value") }
    [System.IO.File]::WriteAllText($EnvFile, (($lines -join "`r`n") + "`r`n"), $Utf8NoBom)
}

function Protect-Item([string]$Path, [switch]$Directory) {
    # Faqat SYSTEM (S-1-5-18) va Administrators (S-1-5-32-544). SID — Windows tilidan qat'i nazar ishlaydi.
    if ($Directory) {
        & icacls $Path /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
    } else {
        & icacls $Path /inheritance:r /grant:r '*S-1-5-18:F' '*S-1-5-32-544:F' | Out-Null
    }
    if ($LASTEXITCODE -ne 0) { throw "icacls bajarilmadi: $Path" }
}

function Test-Winget { return [bool](Get-Command winget -ErrorAction SilentlyContinue) }

function Find-Python {
    if ($PythonExe) { return $PythonExe }
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($v in '3.13', '3.12', '3.11') {
            $p = & py "-$v" -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $p) { return ($p | Select-Object -First 1).Trim() }
        }
    }
    foreach ($c in @("$env:ProgramFiles\Python313\python.exe", "$env:ProgramFiles\Python312\python.exe",
                     "$env:ProgramFiles\Python311\python.exe")) {
        if (Test-Path $c) { return $c }
    }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -notlike '*WindowsApps*') {
        $ver = & $cmd.Source -c "import sys; print('%d.%d' % sys.version_info[:2])"
        if ($LASTEXITCODE -eq 0 -and [version]$ver -ge [version]'3.11') { return $cmd.Source }
    }
    return $null
}

function Find-Pwsh {
    $c = Get-Command pwsh -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    $p = "$env:ProgramFiles\PowerShell\7\pwsh.exe"
    if (Test-Path $p) { return $p }
    return $null
}

function Find-Nssm {
    $c = Get-Command nssm -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    $p = Join-Path $ProjectDir 'tools\nssm.exe'
    if (Test-Path $p) { return $p }
    return $null
}

# ------------------------------------------------------------------ 1. .env
Write-Step ".env"
if (-not (Test-Path $EnvFile)) {
    Copy-Item (Join-Path $ProjectDir '.env.example') $EnvFile
    Write-Note ".env yaratildi (.env.example dan). TELEGRAM_BOT_TOKEN va CLAUDE_CODE_OAUTH_TOKEN ni to'ldirish kerak."
}
if ($AgentHome) { Set-EnvValue 'AGENT_HOME' $AgentHome }
$AgentHome = Get-EnvValue 'AGENT_HOME'
if (-not $AgentHome) { $AgentHome = 'C:\agent'; Set-EnvValue 'AGENT_HOME' $AgentHome }
Protect-Item $EnvFile
Write-Ok ".env: faqat SYSTEM va Administrators o'qiy oladi. AGENT_HOME=$AgentHome"

# ------------------------------------------------------------------ 2. Python + venv
Write-Step "Python 3.11+"
$venvDir = Join-Path $ProjectDir '.venv'
$venvPy = Join-Path $venvDir 'Scripts\python.exe'
# venv allaqachon bor bo'lsa (masalan uv bilan yaratilgan) — tizimga Python o'rnatish shart emas.
$py = if (Test-Path $venvPy) { $venvPy } else { Find-Python }
if (-not $py) {
    if (Test-Winget) {
        Write-Note "Python topilmadi — winget orqali o'rnatilmoqda..."
        winget install --id Python.Python.3.12 -e --scope machine --silent --accept-package-agreements --accept-source-agreements | Out-Null
        $py = Find-Python
    }
    if (-not $py) {
        Write-Note "python.org dan yuklab o'rnatilmoqda..."
        $inst = Join-Path $env:TEMP 'python-3.12-amd64.exe'
        Invoke-WebRequest $PythonUrl -OutFile $inst -UseBasicParsing
        Start-Process $inst -ArgumentList '/quiet InstallAllUsers=1 PrependPath=1 Include_launcher=1 Include_test=0' -Wait
        $py = Find-Python
    }
    if (-not $py) { throw "Python 3.11+ o'rnatilmadi. Qo'lda o'rnatib, -PythonExe 'C:\...\python.exe' bilan qayta ishga tushiring." }
}
Write-Ok "Python: $py"

if (-not (Test-Path $venvPy)) {
    & $py -m venv $venvDir
    if ($LASTEXITCODE -ne 0) { throw "venv yaratilmadi" }
}
& $venvPy -c "import pip" 2>$null
if ($LASTEXITCODE -ne 0) {
    # uv bilan yaratilgan venv'da pip bo'lmaydi
    & $venvPy -m ensurepip --upgrade | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "venv'ga pip o'rnatilmadi (ensurepip)" }
}
& $venvPy -m pip install --upgrade pip --disable-pip-version-check -q
& $venvPy -m pip install -r (Join-Path $ProjectDir 'requirements.txt') --disable-pip-version-check -q
if ($LASTEXITCODE -ne 0) { throw "pip install xato bilan tugadi" }
Write-Ok "venv: $venvPy (requirements o'rnatildi)"

# ------------------------------------------------------------------ 3. PowerShell 7
Write-Step "PowerShell 7 (pwsh)"
if ($SkipPwsh) {
    Write-Note "O'tkazib yuborildi (-SkipPwsh). Agent Windows PowerShell 5.1 bilan ishlaydi."
} elseif (Find-Pwsh) {
    Write-Ok "pwsh: $(Find-Pwsh)"
} else {
    if (Test-Winget) {
        winget install --id Microsoft.PowerShell -e --scope machine --silent --accept-package-agreements --accept-source-agreements | Out-Null
    }
    if (-not (Find-Pwsh)) {
        $msi = Join-Path $env:TEMP 'PowerShell-7-x64.msi'
        Invoke-WebRequest $PwshMsiUrl -OutFile $msi -UseBasicParsing
        Start-Process msiexec.exe -ArgumentList "/i `"$msi`" /quiet ADD_PATH=1 ENABLE_PSREMOTING=0" -Wait
    }
    if (Find-Pwsh) { Write-Ok "pwsh o'rnatildi: $(Find-Pwsh)" } else { Write-Note "pwsh o'rnatilmadi — Windows PowerShell 5.1 ishlatiladi." }
}

# ------------------------------------------------------------------ 4. AGENT_HOME
Write-Step "AGENT_HOME papkalari"
# Python kodi papkalarni, boshlang'ich xotira fayllarini, maxfiy\inventar.json va AGENT_HOME\.gitignore ni yaratadi.
& $venvPy -m agent --init
if ($LASTEXITCODE -ne 0) { throw "AGENT_HOME tayyorlanmadi" }
$gitignore = (@('.env', 'maxfiy/', 'zaxira/', 'jurnal/', 'ish/', 'modellar/', '__pycache__/', '*.pyc', 'venv/', '.venv/') -join "`r`n") + "`r`n"
[System.IO.File]::WriteAllText((Join-Path $AgentHome '.gitignore'), $gitignore, $Utf8NoBom)
Protect-Item (Join-Path $AgentHome 'maxfiy') -Directory
Write-Ok "$AgentHome tayyor; maxfiy\ — faqat SYSTEM va Administrators; .gitignore yozildi"

$token = Get-EnvValue 'TELEGRAM_BOT_TOKEN'
$oauth = Get-EnvValue 'CLAUDE_CODE_OAUTH_TOKEN'
$claudeExe = Join-Path $ProjectDir '.venv\Lib\site-packages\claude_agent_sdk\_bundled\claude.exe'
# Xizmat LocalSystem hisobida ishlaydi va foydalanuvchining `claude auth login`ini ko'rmaydi — setup-token kerak.
$ready = [bool]($token -and $oauth)
if (-not $oauth) {
    Write-Note "CLAUDE_CODE_OAUTH_TOKEN bo'sh — xizmat Claude obunasiga kira olmaydi."
    Write-Note "  O'z hisobingizda:  & '$claudeExe' setup-token   -> tokenni .env ga CLAUDE_CODE_OAUTH_TOKEN=... yozing"
}
if ($ready) {
    Write-Step "Tekshiruv (python -m agent --check)"
    & $venvPy -m agent --check
    if ($LASTEXITCODE -ne 0) { Write-Note "Tekshiruvda muammo bor — yuqoridagi xabarlarni ko'ring." }
}

# ------------------------------------------------------------------ 5. Windows xizmati (NSSM)
if (-not $SkipService) {
    Write-Step "Windows xizmati: $ServiceName (NSSM)"
    $nssm = Find-Nssm
    if (-not $nssm -and (Test-Winget)) {
        winget install --id NSSM.NSSM -e --silent --accept-package-agreements --accept-source-agreements | Out-Null
        $nssm = Find-Nssm
    }
    if (-not $nssm) {
        $zip = Join-Path $env:TEMP 'nssm-2.24.zip'
        $ext = Join-Path $env:TEMP 'nssm-2.24-extract'
        Invoke-WebRequest $NssmZipUrl -OutFile $zip -UseBasicParsing
        Expand-Archive $zip -DestinationPath $ext -Force
        New-Item -ItemType Directory -Force (Join-Path $ProjectDir 'tools') | Out-Null
        Copy-Item (Join-Path $ext 'nssm-2.24\win64\nssm.exe') (Join-Path $ProjectDir 'tools\nssm.exe') -Force
        $nssm = Join-Path $ProjectDir 'tools\nssm.exe'
    }
    Write-Ok "NSSM: $nssm"

    $jurnal = Join-Path $AgentHome 'jurnal'
    if (Get-Service $ServiceName -ErrorAction SilentlyContinue) {
        & $nssm stop $ServiceName | Out-Null
    } else {
        & $nssm install $ServiceName $venvPy '-m agent' | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "nssm install bajarilmadi" }
    }
    & $nssm set $ServiceName Application $venvPy | Out-Null
    & $nssm set $ServiceName AppParameters '-m agent' | Out-Null
    & $nssm set $ServiceName AppDirectory $ProjectDir | Out-Null
    & $nssm set $ServiceName DisplayName 'IT Agent (Telegram + Claude)' | Out-Null
    & $nssm set $ServiceName Description 'Avtonom IT-infratuzilma agenti. Loglar: AGENT_HOME\jurnal' | Out-Null
    & $nssm set $ServiceName Start SERVICE_DELAYED_AUTO_START | Out-Null
    & $nssm set $ServiceName AppStdout (Join-Path $jurnal 'service.log') | Out-Null
    & $nssm set $ServiceName AppStderr (Join-Path $jurnal 'service.log') | Out-Null
    & $nssm set $ServiceName AppRotateFiles 1 | Out-Null
    & $nssm set $ServiceName AppRotateOnline 1 | Out-Null
    & $nssm set $ServiceName AppRotateBytes 10485760 | Out-Null
    & $nssm set $ServiceName AppExit Default Restart | Out-Null
    & $nssm set $ServiceName AppRestartDelay 10000 | Out-Null
    & $nssm set $ServiceName AppThrottle 30000 | Out-Null
    & $nssm set $ServiceName AppEnvironmentExtra 'PYTHONUTF8=1' 'PYTHONIOENCODING=utf-8' | Out-Null
    & sc.exe failure $ServiceName reset= 86400 actions= restart/60000/restart/60000/restart/60000 | Out-Null
    Write-Ok "Xizmat sozlandi (avtomatik start, yiqilsa 10 s da qayta ko'tariladi)"

    if ($ready) {
        # Bitta bot tokeni bilan ikki nusxa ishlasa Telegram 409 beradi — qo'lda ishga tushirilgan nusxani to'xtatamiz
        # (venv'ning python.exe'si ichki jarayon ochadi, shuning uchun daraxti bilan).
        Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
            Where-Object { $_.ExecutablePath -eq $venvPy -and $_.CommandLine -match '-m agent\s*$' } |
            ForEach-Object {
                & taskkill /PID $_.ProcessId /T /F | Out-Null
                Write-Note "Qo'lda ishga tushirilgan agent to'xtatildi (PID $($_.ProcessId)) — endi xizmat ishlaydi."
            }
        Start-Service $ServiceName
        Start-Sleep -Seconds 5
        Write-Ok "Holat: $((Get-Service $ServiceName).Status). Telegramga 'IT-agent ishga tushdi' xabari kelishi kerak."
    } else {
        Write-Note "Xizmat ISHGA TUSHIRILMADI: .env da TELEGRAM_BOT_TOKEN va/yoki CLAUDE_CODE_OAUTH_TOKEN bo'sh."
    }
}

# ------------------------------------------------------------------ 6. Haftalik xulosa
if (-not $SkipWeeklyTask) {
    Write-Step "Haftalik xulosa vazifasi ($WeeklyDay $WeeklyTime)"
    $system = (New-Object System.Security.Principal.SecurityIdentifier('S-1-5-18')).Translate(
        [System.Security.Principal.NTAccount]).Value
    $action = New-ScheduledTaskAction -Execute $venvPy -Argument '-m agent.weekly' -WorkingDirectory $ProjectDir
    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $WeeklyDay -At $WeeklyTime
    $principal = New-ScheduledTaskPrincipal -UserId $system -LogonType ServiceAccount -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
    Register-ScheduledTask -TaskName "$ServiceName-Haftalik" -Action $action -Trigger $trigger -Principal $principal `
        -Settings $settings -Description 'IT-agent: haftalik 5 qatorlik xulosa Telegramga' -Force | Out-Null
    Write-Ok "Vazifa: $ServiceName-Haftalik"
}

# ------------------------------------------------------------------ yakun
Write-Step "Tayyor"
if (-not $ready) {
    Write-Host @"
  Qolgan ish — $EnvFile ni (administrator sifatida ochilgan muharrirda) to'ldiring:
    TELEGRAM_BOT_TOKEN      = BotFather -> /revoke -> YANGI token
    CLAUDE_CODE_OAUTH_TOKEN = o'z hisobingizda: & '$claudeExe' setup-token
  So'ng:  install.ps1 ni qayta ishga tushiring
"@ -ForegroundColor Yellow
}
Write-Host @"
  Holat:          Get-Service $ServiceName
  To'xtatish:     Stop-Service $ServiceName
  Qayta ishga:    Restart-Service $ServiceName
  Loglar:         $AgentHome\jurnal\  (YYYY-MM-DD.md, YYYY-MM-DD.jsonl, agent.log, service.log)
  Konsol sinovi:  & '$venvPy' -m agent --once "disk joyini tekshir"
"@
