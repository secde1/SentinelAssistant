#Requires -RunAsAdministrator
<#
.SYNOPSIS
  IT-agent xizmatini va haftalik vazifani o'chiradi. Ma'lumotlar (AGENT_HOME: xotira, skill, jurnal, maxfiy,
  zaxira) va loyiha papkasi O'CHIRILMAYDI.
#>
[CmdletBinding()]
param([string]$ServiceName = "ITAgent")

$ErrorActionPreference = 'Stop'
$nssm = (Get-Command nssm -ErrorAction SilentlyContinue).Source
if (-not $nssm) { $nssm = Join-Path $PSScriptRoot 'tools\nssm.exe' }

if (Get-Service $ServiceName -ErrorAction SilentlyContinue) {
    Stop-Service $ServiceName -ErrorAction SilentlyContinue
    if (Test-Path $nssm) { & $nssm remove $ServiceName confirm | Out-Null } else { & sc.exe delete $ServiceName | Out-Null }
    Write-Host "[OK] Xizmat o'chirildi: $ServiceName" -ForegroundColor Green
} else {
    Write-Host "Xizmat topilmadi: $ServiceName"
}
if (Get-ScheduledTask -TaskName "$ServiceName-Haftalik" -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName "$ServiceName-Haftalik" -Confirm:$false
    Write-Host "[OK] Vazifa o'chirildi: $ServiceName-Haftalik" -ForegroundColor Green
}
Write-Host "Ma'lumotlar saqlab qolindi (AGENT_HOME va loyiha papkasi)."
