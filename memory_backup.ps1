<#
.SYNOPSIS
  Agentning o'rgangan bilimini (skill/, xotira/, skript/) GitHubga xavfsiz zaxiralaydi.

.DESCRIPTION
  - AGENT_HOME loyiha ichida bo'lsa (masalan D:\it-agent\data), loyiha reposiga commit qiladi va faqat
    <AGENT_HOME>/skill, xotira, skript va .gitignore ni oladi. Boshqa stage qilingan kod o'zgarishlari commitga
    qo'shilmaydi. AGENT_HOME loyihadan tashqarida bo'lsa (masalan C:\agent), u yerda alohida repo ochadi.
  - maxfiy/, zaxira/, jurnal/, ish/, modellar/, .env HECH QACHON yuborilmaydi.
  - Commitdan oldin tekshiradi: taqiqlangan yo'l stage'ga tushmaganmi; fayllarda maxfiy/inventar.json dagi parol/token
    qiymatlari yoki token naqshlari (bot token, sk-ant-..., private key, password=...) yo'qmi. Topilsa - to'xtaydi.

.EXAMPLE
  .\memory_backup.ps1              # commit + push
.EXAMPLE
  .\memory_backup.ps1 -NoPush      # faqat lokal commit
.EXAMPLE
  .\memory_backup.ps1 -Check       # faqat tekshiruv: nima yuborilishini ko'rsatadi, commit qilmaydi
.EXAMPLE
  .\memory_backup.ps1 -RemoteUrl git@github.com:user/it-agent-xotira.git   # alohida repo, birinchi marta
#>
[CmdletBinding()]
param(
    [string]$AgentHome = "",
    [string]$RemoteUrl = "",
    [string]$Branch = "",
    [switch]$NoPush,
    [switch]$Check
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
$AgentHome = (Resolve-Path $AgentHome).Path.TrimEnd('\')

# AGENT_HOME loyiha reposi ichidami?
$projectRoot = (Resolve-Path $ProjectDir).Path.TrimEnd('\')
$inProject = (Test-Path (Join-Path $projectRoot '.git')) -and $AgentHome.StartsWith($projectRoot + '\', 'OrdinalIgnoreCase')
if ($inProject) {
    $RepoDir = $projectRoot
    $prefix = $AgentHome.Substring($projectRoot.Length + 1).Replace('\', '/') + '/'
} else {
    $RepoDir = $AgentHome
    $prefix = ''
}

$safeDir = $RepoDir -replace '\\', '/'
# core.quotepath=false + UTF-8: kirillcha fayl nomlari skanerdan chetda qolmasligi uchun
function Invoke-Git {
    & git -c "safe.directory=$safeDir" -c core.quotepath=false @args
    if ($LASTEXITCODE -ne 0) { throw "git $($args -join ' ') - xato (kod $LASTEXITCODE)" }
}
function Get-Git {
    & git -c "safe.directory=$safeDir" -c core.quotepath=false @args
}

$prevEncoding = [Console]::OutputEncoding
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Push-Location $RepoDir
try {
    # .gitignore - agent yozadigan bilan bir xil
    $gi = (@('.env', 'maxfiy/', 'zaxira/', 'jurnal/', 'ish/', 'modellar/', '__pycache__/', '*.pyc', 'venv/', '.venv/') -join "`r`n") + "`r`n"
    [System.IO.File]::WriteAllText((Join-Path $AgentHome '.gitignore'), $gi, (New-Object System.Text.UTF8Encoding($false)))

    if (-not (Test-Path (Join-Path $RepoDir '.git'))) {
        if ($Check) { throw "Repo hali yo'q: $RepoDir (tekshiruv uchun avval -Check siz ishga tushiring)" }
        Invoke-Git init -q
        Invoke-Git symbolic-ref HEAD "refs/heads/$(if ($Branch) { $Branch } else { 'main' })"
        Write-Host "[OK] Git repo yaratildi: $RepoDir"
    }
    if (-not $Branch) { $Branch = (Get-Git rev-parse --abbrev-ref HEAD) }
    if (-not (Get-Git config user.email)) {
        Invoke-Git config user.email 'it-agent@localhost'
        Invoke-Git config user.name 'IT Agent'
    }
    if ($RemoteUrl -and -not $Check) {
        if ((Get-Git remote) -contains 'origin') { Invoke-Git remote set-url origin $RemoteUrl } else { Invoke-Git remote add origin $RemoteUrl }
    }

    $paths = @("$prefix.gitignore") + (@('skill', 'xotira', 'skript') | Where-Object { Test-Path (Join-Path $AgentHome $_) } |
        ForEach-Object { "$prefix$_" })
    Invoke-Git add -A -- @paths
    $staged = @(Get-Git diff --cached --name-only -- @paths)

    $forbidden = $staged | Where-Object { $_ -match '(^|/)(maxfiy|zaxira|jurnal|ish|modellar)/' -or $_ -match '(^|/)\.env$' }
    if ($forbidden) {
        Invoke-Git reset -q -- @paths
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
                    $k -match 'password|passwd|pwd|secret|token|api_?key|apikey|api_hash|passphrase|community|psk|private_?key' -and
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
        $full = Join-Path $RepoDir $f
        if (-not (Test-Path $full -PathType Leaf)) { continue }
        $text = [System.IO.File]::ReadAllText($full)
        $hit = $false
        foreach ($v in $secretValues) { if ($text.Contains($v)) { $hit = $true; break } }
        if (-not $hit) { foreach ($p in $patterns) { if ($text -match $p) { $hit = $true; break } } }
        if ($hit) { $bad += $f }
    }
    if ($bad) {
        Invoke-Git reset -q -- @paths
        throw "TO'XTATILDI: quyidagi fayllarda maxfiy qiymat bor (qiymat ko'rsatilmaydi): $($bad -join ', '). Tozalab, qayta ishga tushiring."
    }

    if ($Check) {
        Invoke-Git reset -q -- @paths
        Write-Host "[OK] Tekshiruv: maxfiy qiymat topilmadi. Yuboriladigan o'zgarishlar: $($staged.Count) ta fayl" -ForegroundColor Green
        $staged | ForEach-Object { Write-Host "  $_" }
        return
    }

    if (-not $staged) {
        Write-Host "O'zgarish yo'q - commit qilinmadi."
    } else {
        # pathspec bilan: boshqa stage qilingan kod o'zgarishlari bu commitga tushmaydi
        Invoke-Git commit -q -m "xotira zaxirasi $(Get-Date -Format 'yyyy-MM-dd HH:mm')" -- @paths
        Write-Host "[OK] Commit: $($staged.Count) ta fayl"
    }

    if (-not $NoPush) {
        if ((Get-Git remote) -contains 'origin') {
            $ahead = ''
            try { $ahead = Get-Git rev-list --count "origin/$Branch..$Branch" 2>$null } catch { }
            if ($ahead) { Write-Host "  Yuboriladigan commitlar ($Branch): $ahead" }
            Invoke-Git push -u origin $Branch
            Write-Host "[OK] GitHubga yuborildi ($Branch)" -ForegroundColor Green
        } else {
            Write-Host "[!] Remote yo'q - birinchi marta -RemoteUrl bilan ishga tushiring." -ForegroundColor Yellow
        }
    }
} finally {
    Pop-Location
    [Console]::OutputEncoding = $prevEncoding
}
