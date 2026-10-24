<#
.SYNOPSIS
  Agentning o'rgangan bilimini (skill/, xotira/, skript/) GitHubga xavfsiz zaxiralaydi.

.DESCRIPTION
  - Faqat skill/, xotira/, skript/ va .gitignore commit qilinadi. maxfiy/, zaxira/, jurnal/, ish/, .env — HECH QACHON.
  - Commitdan oldin tekshiradi: taqiqlangan yo'l stage'ga tushmaganmi; fayllarda maxfiy/inventar.json dagi parol/token
    qiymatlari yoki token naqshlari (bot token, sk-ant-..., private key, password=...) yo'qmi. Topilsa — to'xtaydi.
  - Birinchi marta: -RemoteUrl bilan GitHub repo manzilini bering (masalan git@github.com:jamshid/it-agent-xotira.git).

.EXAMPLE
  .\memory_backup.ps1 -RemoteUrl git@github.com:jamshid/it-agent-xotira.git
.EXAMPLE
  .\memory_backup.ps1            # keyingi safarlar
.EXAMPLE
  .\memory_backup.ps1 -NoPush    # faqat lokal commit
#>
[CmdletBinding()]
param(
    [string]$AgentHome = "",
    [string]$RemoteUrl = "",
    [string]$Branch = "main",
    [switch]$NoPush
)

$ErrorActionPreference = 'Stop'
$ProjectDir = $PSScriptRoot

if (-not $AgentHome) {
    $envFile = Join-Path $ProjectDir '.env'
    if (Test-Path $envFile) {
        foreach ($line in [System.IO.File]::ReadAllLines($envFile)) {
            if ($line -match '^\s*AGENT_HOME\s*=\s*(.+)$') { $AgentHome = $Matches[1].Trim().Trim('"').Trim("'") }
        }
    }
}
if (-not $AgentHome) { $AgentHome = 'C:\agent' }
if (-not (Test-Path $AgentHome)) { throw "AGENT_HOME topilmadi: $AgentHome" }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw "git topilmadi. O'rnatish: winget install --id Git.Git -e" }

$safeDir = $AgentHome -replace '\\', '/'
function Invoke-Git {
    & git -c "safe.directory=$safeDir" @args
    if ($LASTEXITCODE -ne 0) { throw "git $($args -join ' ') — xato (kod $LASTEXITCODE)" }
}

Push-Location $AgentHome
try {
    # .gitignore — agent yozadigan bilan bir xil
    $gi = (@('.env', 'maxfiy/', 'zaxira/', 'jurnal/', 'ish/', 'modellar/', '__pycache__/', '*.pyc', 'venv/', '.venv/') -join "`r`n") + "`r`n"
    [System.IO.File]::WriteAllText((Join-Path $AgentHome '.gitignore'), $gi, (New-Object System.Text.UTF8Encoding($false)))

    if (-not (Test-Path (Join-Path $AgentHome '.git'))) {
        Invoke-Git init -q
        Invoke-Git symbolic-ref HEAD "refs/heads/$Branch"
        Write-Host "[OK] Git repo yaratildi: $AgentHome"
    }
    $email = & git -c "safe.directory=$safeDir" config user.email
    if (-not $email) {
        Invoke-Git config user.email 'it-agent@localhost'
        Invoke-Git config user.name 'IT Agent'
    }
    if ($RemoteUrl) {
        $remotes = & git -c "safe.directory=$safeDir" remote
        if ($remotes -contains 'origin') { Invoke-Git remote set-url origin $RemoteUrl } else { Invoke-Git remote add origin $RemoteUrl }
    }

    $paths = @('.gitignore') + (@('skill', 'xotira', 'skript') | Where-Object { Test-Path (Join-Path $AgentHome $_) })
    Invoke-Git add -A -- @paths

    $staged = @(& git -c "safe.directory=$safeDir" diff --cached --name-only)
    $forbidden = $staged | Where-Object { $_ -match '^(maxfiy|zaxira|jurnal|ish)/' -or $_ -match '(^|/)\.env$' }
    if ($forbidden) {
        Invoke-Git reset -q
        throw "TO'XTATILDI: taqiqlangan fayllar stage'ga tushgan: $($forbidden -join ', ')"
    }

    # --- maxfiy qiymatlar skaneri ---
    $secretValues = New-Object System.Collections.Generic.List[string]
    function Add-Secrets($node, [bool]$isSecret) {
        if ($null -eq $node) { return }
        if ($node -is [System.Management.Automation.PSCustomObject]) {
            foreach ($p in $node.PSObject.Properties) {
                $k = $p.Name.ToLower()
                $secretKey = $isSecret -or $k -eq 'generated' -or (
                    $k -match 'password|passwd|pwd|secret|token|api_?key|apikey|passphrase|community|psk|private_?key' -and
                    $k -notmatch 'lastset|expir|never|length|policy|count|name|type|file|path|url')
                Add-Secrets $p.Value $secretKey
            }
        } elseif ($node -is [System.Array]) {
            foreach ($i in $node) { Add-Secrets $i $isSecret }
        } elseif ($isSecret -and "$node".Length -ge 4) {
            $secretValues.Add("$node")
        }
    }
    $inv = Join-Path $AgentHome 'maxfiy\inventar.json'
    if (Test-Path $inv) { Add-Secrets ([System.IO.File]::ReadAllText($inv) | ConvertFrom-Json) $false }

    $patterns = @(
        '(?<!\d)\d{8,10}:[A-Za-z0-9_-]{30,}',
        'sk-ant-[A-Za-z0-9_-]{10,}',
        '-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----',
        '(?i)\b(password|passwd|parol|secret|token|api[_-]?key)\b\s*[:=]\s*[''"]?(?!\*\*\*|\{\{|\$)[^\s''"]{4,}'
    )
    $bad = @()
    foreach ($f in $staged) {
        $full = Join-Path $AgentHome $f
        if (-not (Test-Path $full -PathType Leaf)) { continue }
        $text = [System.IO.File]::ReadAllText($full)
        $hit = $false
        foreach ($v in $secretValues) { if ($text.Contains($v)) { $hit = $true; break } }
        if (-not $hit) { foreach ($p in $patterns) { if ($text -match $p) { $hit = $true; break } } }
        if ($hit) { $bad += $f }
    }
    if ($bad) {
        Invoke-Git reset -q
        throw "TO'XTATILDI: quyidagi fayllarda maxfiy qiymat bor (qiymat ko'rsatilmaydi): $($bad -join ', '). Tozalab, qayta ishga tushiring."
    }

    if (-not $staged) {
        Write-Host "O'zgarish yo'q — commit qilinmadi."
    } else {
        Invoke-Git commit -q -m "xotira zaxirasi $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
        Write-Host "[OK] Commit: $($staged.Count) ta fayl"
    }

    if (-not $NoPush) {
        $remotes = & git -c "safe.directory=$safeDir" remote
        if ($remotes -contains 'origin') {
            Invoke-Git push -u origin $Branch
            Write-Host "[OK] GitHubga yuborildi ($Branch)" -ForegroundColor Green
        } else {
            Write-Host "[!] Remote yo'q — birinchi marta -RemoteUrl bilan ishga tushiring." -ForegroundColor Yellow
        }
    }
} finally {
    Pop-Location
}
