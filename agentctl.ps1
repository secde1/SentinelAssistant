<#
SENTINAL AI agentini boshqarish. Agentni Windows Task Scheduler'dagi "AgentRestart" vazifasi ishga tushiradi:
Windows'ga kirganda oynasiz (pythonw.exe), kutilmaganda yiqilsa 1 daqiqadan keyin qayta ko'taradi.

  agentctl status              holat: vazifa, jarayon, oxirgi ishga tushish/to'xtash
  agentctl start               ishga tushirish (ishlayotgan bo'lsa hech narsa qilmaydi)
  agentctl stop                to'xtatish. O'zi qayta ishga tushmaydi (Windows'ga kirganda ham) - start bilan yoqiladi
  agentctl restart [-Delay N]  qayta ishga tushirish (N soniya kutib)
  agentctl autostart on|off    Windows'ga kirganda avtomatik ishga tushishni yoqish / o'chirish
  agentctl logs [-Lines N]     console.log oxiri va ishga tushish/to'xtash yozuvlari
  agentctl install             AgentRestart vazifasini yaratish yoki yangilash (administrator shart emas)

Hech biri administrator huquqini talab qilmaydi.
#>
param(
    [Parameter(Position = 0)]
    [ValidateSet('status', 'start', 'stop', 'restart', 'autostart', 'logs', 'install')]
    [string]$Command = 'status',
    [Parameter(Position = 1)][string]$State = '',
    [int]$Delay = 0,
    [int]$Lines = 30
)
$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

$TaskName = 'AgentRestart'
$Root = $PSScriptRoot
$Pythonw = Join-Path $Root '.venv\Scripts\pythonw.exe'
$Utf8 = New-Object System.Text.UTF8Encoding $false
$Dash = [char]0x2014

function Get-AgentHome {
    # config.py bilan bir xil tartib: muhit o'zgaruvchisi, keyin .env, keyin C:\agent
    if ($env:AGENT_HOME) { return $env:AGENT_HOME.Trim() }
    $envFile = Join-Path $Root '.env'
    if (Test-Path $envFile) {
        foreach ($line in [System.IO.File]::ReadAllLines($envFile)) {
            if ($line -match '^\s*AGENT_HOME\s*=\s*(.+?)\s*$') { return $Matches[1].Trim('"', "'") }
        }
    }
    return 'C:\agent'
}

$AgentHome = Get-AgentHome
$Ish = Join-Path $AgentHome 'ish'
$Jurnal = Join-Path $AgentHome 'jurnal'
$StopFile = Join-Path $Ish 'agent.stop'
$StartsFile = Join-Path $Ish 'agent.starts'
$StateFile = Join-Path $Ish 'agent.state'

# ---------------------------------------------------------------- yordamchilar
function Write-Journal([string]$Type, [string]$Text) {
    $now = Get-Date
    New-Item -ItemType Directory -Force $Jurnal | Out-Null
    $day = $now.ToString('yyyy-MM-dd')
    $rec = [ordered]@{ ts = $now.ToString('yyyy-MM-ddTHH:mm:ss'); type = $Type; by = "$env:USERNAME (agentctl)" }
    [System.IO.File]::AppendAllText((Join-Path $Jurnal "$day.jsonl"), ($rec | ConvertTo-Json -Compress) + "`n", $Utf8)
    $md = Join-Path $Jurnal "$day.md"
    if (-not (Test-Path $md)) {
        [System.IO.File]::WriteAllText($md, "# Jurnal $day`n`n| Vaqt | Host | Nima qildim | Natija |`n|---|---|---|---|`n", $Utf8)
    }
    [System.IO.File]::AppendAllText($md, "| $($now.ToString('HH:mm:ss')) | $Dash | $Text | |`n", $Utf8)
}

function Read-Json([string]$Path) {
    if (-not (Test-Path $Path)) { return $null }
    try { return [System.IO.File]::ReadAllText($Path) | ConvertFrom-Json } catch { return $null }
}

function Set-StopMarker([bool]$Allow, [string]$Action) {
    New-Item -ItemType Directory -Force $Ish | Out-Null
    $obj = [ordered]@{ ts = (Get-Date).ToString('yyyy-MM-ddTHH:mm:ss'); by = "$env:USERNAME (agentctl)"; action = $Action; allow = $Allow }
    [System.IO.File]::WriteAllText($StopFile, ($obj | ConvertTo-Json -Compress), $Utf8)
}

function Get-AgentProcesses {
    # "-m agent" jarayonlari (--check/--once emas). FromTask: AgentRestart vazifasi ochgan nusxa (uv launcher'ning
    # ota-jarayoni Task Scheduler xizmati; asl python esa shu launcher'ning bolasi).
    $sched = [int](Get-CimInstance Win32_Service -Filter "Name='Schedule'").ProcessId
    $all = @(Get-CimInstance Win32_Process | Where-Object {
            $_.Name -match '^pythonw?\.exe$' -and $_.CommandLine -match '\s-m\s+agent(\s|"|$)' -and
            $_.CommandLine -notmatch '--(check|once|init)\b' })
    $byId = @{}
    foreach ($p in $all) { $byId[[int]$p.ProcessId] = $p }
    foreach ($p in $all) {
        $top = $p
        if ($byId.ContainsKey([int]$p.ParentProcessId)) { $top = $byId[[int]$p.ParentProcessId] }
        [pscustomobject]@{
            Id = [int]$p.ProcessId; Started = $p.CreationDate; MB = [int]($p.WorkingSetSize / 1MB)
            FromTask = ([int]$top.ParentProcessId -eq $sched); IsLauncher = -not $byId.ContainsKey([int]$p.ParentProcessId)
        }
    }
}

function Get-TaskCom {
    $svc = New-Object -ComObject Schedule.Service
    $svc.Connect()
    $folder = $svc.GetFolder('\')
    try { $task = $folder.GetTask($TaskName) } catch { $task = $null }
    return @{ Folder = $folder; Task = $task }
}

function Assert-Task {
    if (-not (Get-TaskCom).Task) { throw "Vazifa '$TaskName' yo'q. Avval: agentctl install" }
}

function Wait-AgentStart([datetime]$Since, [int]$Seconds = 20) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 2
        $p = @(Get-AgentProcesses | Where-Object { $_.FromTask -and $_.Started -ge $Since.AddSeconds(-2) })
        if ($p) {
            "Jarayon ochildi: PID $(($p | ForEach-Object Id) -join ', '). Telegram'ga 'IT-agent ishga tushdi' xabari kelsa - tayyor."
            return
        }
    }
    "Diqqat: $Seconds soniyada jarayon ko'rinmadi. Sabab: agentctl logs"
}

function Show-Lifecycle([int]$Count) {
    # Jurnalning .md qatorlaridan faqat agent hayot sikli (matni "Agent " bilan boshlanadi)
    $rows = foreach ($d in (Get-Date).AddDays(-1), (Get-Date)) {
        $md = Join-Path $Jurnal ($d.ToString('yyyy-MM-dd') + '.md')
        if (Test-Path $md) {
            foreach ($line in [System.IO.File]::ReadAllLines($md, $Utf8)) {
                $cols = $line.Split('|')
                if ($cols.Count -ge 4 -and $cols[3].Trim().StartsWith('Agent ')) { "$($d.ToString('dd.MM')) $($cols[1].Trim())  $($cols[3].Trim())" }
            }
        }
    }
    @($rows) | Select-Object -Last $Count
}

# ---------------------------------------------------------------- vazifa (XML)
function Get-TaskXml {
    $user = "$env:USERDOMAIN\$env:USERNAME"
    # Kutilmagan yiqilish: shu vazifaning "Action completed" (201) hodisasi nol bo'lmagan kod bilan. Istisnolar:
    # 2147942402 = chiqish kodi 2 (sozlama xatosi - qayta urinish foyda bermaydi), 2147943691 = Task Scheduler
    # to'xtatdi (agentctl stop/restart), 1073807364 va 3221225786 = Windows'dan chiqish / o'chirish.
    $query = "<QueryList><Query Id=`"0`" Path=`"Microsoft-Windows-TaskScheduler/Operational`"><Select Path=`"Microsoft-Windows-TaskScheduler/Operational`">" +
    "*[System[EventID=201]] and *[EventData[Data[@Name='TaskName']='\$TaskName' and Data[@Name='ResultCode']!='0'" +
    " and Data[@Name='ResultCode']!='2147942402' and Data[@Name='ResultCode']!='2147943691'" +
    " and Data[@Name='ResultCode']!='1073807364' and Data[@Name='ResultCode']!='3221225786']]</Select></Query></QueryList>"
    $sub = [System.Security.SecurityElement]::Escape($query)
    $desc = [System.Security.SecurityElement]::Escape(
        "SENTINAL AI agenti ($Root): Windows'ga kirganda oynasiz ishga tushadi, kutilmaganda yiqilsa 1 daqiqadan keyin " +
        "qayta ko'tariladi. Boshqarish: $Root\agentctl.cmd status | start | stop | restart | autostart on/off | logs")
    return @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Author>$user</Author>
    <Description>$desc</Description>
    <URI>\$TaskName</URI>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>$user</UserId>
      <Delay>PT15S</Delay>
    </LogonTrigger>
    <EventTrigger>
      <Enabled>true</Enabled>
      <Delay>PT1M</Delay>
      <Subscription>$sub</Subscription>
    </EventTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>$user</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>StopExisting</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>false</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>5</Priority>
    <RestartOnFailure>
      <Interval>PT1M</Interval>
      <Count>3</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>$Pythonw</Command>
      <Arguments>-m agent</Arguments>
      <WorkingDirectory>$Root</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"@
}

# ---------------------------------------------------------------- buyruqlar
function Invoke-Install {
    if (-not (Test-Path $Pythonw)) { throw "Topilmadi: $Pythonw (avval install.ps1 yoki .venv yarating)" }
    $com = Get-TaskCom
    # 6 = TASK_CREATE_OR_UPDATE, 3 = TASK_LOGON_INTERACTIVE_TOKEN (parol saqlanmaydi)
    $com.Folder.RegisterTask($TaskName, (Get-TaskXml), 6, $null, $null, 3) | Out-Null
    Write-Journal 'agent_task_installed' "Agent avtostart vazifasi yangilandi: $TaskName (agentctl install)"
    "Vazifa '$TaskName' yaratildi/yangilandi:"
    "  Windows'ga kirganda (15 s kechikish bilan) ishga tushadi: $Pythonw -m agent"
    "  Kutilmaganda yiqilsa - 1 daqiqadan keyin qayta; 15 daqiqada 5 martadan ko'p bo'lsa agent o'zi to'xtaydi"
    "  Batareyada ham ishlaydi, vaqt chegarasi yo'q, oddiy huquq (administrator emas)"
    $log = Get-WinEvent -ListLog 'Microsoft-Windows-TaskScheduler/Operational'
    if (-not $log.IsEnabled) {
        "Diqqat: Task Scheduler tarixi (Operational log) o'chiq - yiqilgandan keyin avtomatik qayta ko'tarish ishlamaydi."
        "  Yoqish (administrator): wevtutil set-log Microsoft-Windows-TaskScheduler/Operational /enabled:true"
    }
}

function Show-Status {
    $com = Get-TaskCom
    if (-not $com.Task) {
        "Vazifa:     '$TaskName' yo'q - yaratish: agentctl install"
    } else {
        $t = $com.Task
        $states = @{ 0 = "noma'lum"; 1 = "o'chirilgan"; 2 = 'navbatda'; 3 = 'tayyor (kutmoqda)'; 4 = 'ishlayapti' }
        $logon = @($t.Definition.Triggers | Where-Object { $_.Type -eq 9 })
        $autostart = if (-not $logon) { "yo'q (agentctl install)" } elseif ($logon[0].Enabled) { "yoqilgan (Windows'ga kirganda)" } else { "o'chirilgan" }
        $action = @($t.Definition.Actions)[0]
        "Vazifa:     $TaskName - $($states[[int]$t.State]); oxirgi ishga tushish $($t.LastRunTime.ToString('dd.MM HH:mm:ss')), natija 0x{0:X}" -f $t.LastTaskResult
        "Avtostart:  $autostart"
        if ($action.Path -notmatch 'pythonw\.exe$') { "Diqqat:     vazifa eski usulda ($($action.Path)) - yangilash: agentctl install" }
    }
    $procs = @(Get-AgentProcesses)
    $main = @($procs | Where-Object { -not $_.IsLauncher })
    if (-not $main) { $main = $procs }
    if ($procs) {
        $p = $main[0]
        $where = if ($p.FromTask) { 'vazifa orqali' } else { 'VAZIFADAN TASHQARI (masalan, terminalda qo''lda ochilgan)' }
        "Jarayon:    ishlayapti - PID $($p.Id), $($p.Started.ToString('dd.MM HH:mm:ss')) dan beri, $($p.MB) MB, $where"
    } else {
        "Jarayon:    ishlamayapti"
    }
    $state = Read-Json $StateFile
    if ($state) {
        $clean = if ($state.clean) { 'toza to''xtagan' } else { 'ishlayapti yoki kutilmaganda to''xtagan' }
        "Oxirgi ish: v$($state.version), boshlangan $($state.started), oxirgi tirik belgi $($state.last_alive) ($clean)"
    }
    $stop = Read-Json $StopFile
    if ($stop -and -not $stop.allow) { "To'xtatilgan: egasi, $($stop.ts) - o'zi ishga tushmaydi. Yoqish: agentctl start" }
    ""
    "Oxirgi yozuvlar:"
    Show-Lifecycle 8 | ForEach-Object { "  $_" }
}

function Start-Agent {
    Assert-Task
    $procs = @(Get-AgentProcesses)
    if ($procs | Where-Object FromTask) {
        "Agent allaqachon ishlayapti (PID $(($procs | Where-Object { -not $_.IsLauncher } | ForEach-Object Id) -join ', ')). Qayta ishga tushirish: agentctl restart"
        return
    }
    if ($procs) {
        "Agent vazifadan tashqarida ishlayapti (PID $(($procs | ForEach-Object Id) -join ', ')). Vazifaga o'tkazish: agentctl restart"
        return
    }
    $stop = Read-Json $StopFile
    if ($stop) {
        $stop.allow = $true
        [System.IO.File]::WriteAllText($StopFile, ($stop | ConvertTo-Json -Compress), $Utf8)
    }
    Remove-Item $StartsFile -ErrorAction SilentlyContinue
    $since = Get-Date
    Write-Journal 'agent_start_requested' "Agent ishga tushirildi (agentctl start)"
    Start-ScheduledTask -TaskName $TaskName
    Wait-AgentStart $since
}

function Stop-Agent {
    Set-StopMarker -Allow $false -Action 'stop'
    Write-Journal 'agent_stop_requested' "Agent to'xtatildi (agentctl stop) - o'zi qayta ishga tushmaydi"
    $com = Get-TaskCom
    if ($com.Task -and $com.Task.State -eq 4) { $com.Task.Stop(0) }
    Start-Sleep -Seconds 2
    foreach ($p in @(Get-AgentProcesses)) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 1
    $left = @(Get-AgentProcesses)
    if ($left) { "Diqqat: jarayon qoldi (PID $(($left | ForEach-Object Id) -join ', '))" }
    else { "Agent to'xtatildi. U o'zi qayta ishga tushmaydi (Windows'ga qayta kirganda ham). Yoqish: agentctl start" }
}

function Restart-Agent {
    Assert-Task
    if ($Delay -gt 0) { Start-Sleep -Seconds $Delay }
    Set-StopMarker -Allow $true -Action 'restart'
    Remove-Item $StartsFile -ErrorAction SilentlyContinue
    $since = Get-Date
    Write-Journal 'agent_restart_requested' "Agent qayta ishga tushirildi (agentctl restart)"
    # Vazifadan tashqaridagi nusxalar (eski usulda yoki qo'lda ochilgan) Telegram'ni talashmasin
    foreach ($p in @(Get-AgentProcesses | Where-Object { -not $_.FromTask })) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
    # StopExisting: ishlayotgan nusxani Task Scheduler o'zi to'xtatib, yangisini ochadi. Agent o'zi chaqirgan bo'lsa,
    # bu skript ham shu yerda to'xtaydi - bu normal.
    Start-ScheduledTask -TaskName $TaskName
    Wait-AgentStart $since
}

function Set-Autostart([string]$Value) {
    if ($Value -notin @('on', 'off')) { throw "Ishlatish: agentctl autostart on | off" }
    $com = Get-TaskCom
    if (-not $com.Task) { throw "Vazifa '$TaskName' yo'q. Avval: agentctl install" }
    $def = $com.Task.Definition
    $logon = @($def.Triggers | Where-Object { $_.Type -eq 9 })
    if (-not $logon) { throw "Vazifada logon-trigger yo'q. Yangilash: agentctl install" }
    foreach ($t in $logon) { $t.Enabled = ($Value -eq 'on') }
    # 4 = TASK_UPDATE, 3 = TASK_LOGON_INTERACTIVE_TOKEN
    $com.Folder.RegisterTaskDefinition($TaskName, $def, 4, $null, $null, 3) | Out-Null
    if ($Value -eq 'on') {
        Write-Journal 'agent_autostart' "Agent avtostarti yoqildi (agentctl autostart on)"
        "Avtostart yoqildi: agent Windows'ga kirganda o'zi ishga tushadi."
    } else {
        Write-Journal 'agent_autostart' "Agent avtostarti o'chirildi (agentctl autostart off)"
        "Avtostart o'chirildi. Hozirgi jarayonga tegilmadi; qo'lda: agentctl start / stop"
    }
}

function Show-Logs {
    $console = Join-Path $Jurnal 'console.log'
    "== $console (oxirgi $Lines qator)"
    if (Test-Path $console) { Get-Content $console -Tail $Lines -Encoding UTF8 } else { "(yo'q)" }
    ""
    "== Ishga tushish / to'xtash yozuvlari ($Jurnal\YYYY-MM-DD.md)"
    Show-Lifecycle 15
}

switch ($Command) {
    'status' { Show-Status }
    'start' { Start-Agent }
    'stop' { Stop-Agent }
    'restart' { Restart-Agent }
    'autostart' { Set-Autostart $State }
    'logs' { Show-Logs }
    'install' { Invoke-Install }
}
