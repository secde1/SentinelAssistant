$ErrorActionPreference='Continue'
$log='D:\it-agent\data\ish\startup_hklm_off.log'
$bk='D:\it-agent\data\zaxira\2026-11-04'
New-Item -ItemType Directory -Force $bk | Out-Null
$base='HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved'
reg export "$base\Run" "$bk\hklm_sa_run_elev.reg" /y | Out-Null
reg export "$base\Run32" "$bk\hklm_sa_run32_elev.reg" /y | Out-Null
$off=[byte[]](3,0,0,0,0,0,0,0,0,0,0,0)
$items=@{ 'Run'=@('Pantum-P2500-Series','HCWebControl','MFNetworkScannerSelector','MTPW');
          'Run32'=@('Lightshot','iVMS-4200.Framework.S','SunJavaUpdateSched') }
"admin=" + ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole('Administrator') | Out-File $log
foreach($k in $items.Keys){ foreach($n in $items[$k]){
  try{ Set-ItemProperty -Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\$k" -Name $n -Value $off -Type Binary -ErrorAction Stop; "OK $k $n" | Out-File $log -Append }
  catch{ "FAIL $k $n $($_.Exception.Message)" | Out-File $log -Append } } }
