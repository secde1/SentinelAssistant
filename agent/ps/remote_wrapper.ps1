# Agent tomonidan ishlatiladi: skriptni masofaviy Windows hostda WinRM orqali bajaradi.
# Login/parol muhit o'zgaruvchilari orqali keladi (buyruq satrida ko'rinmaydi) va darhol tozalanadi.
$ProgressPreference = 'SilentlyContinue'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

$scriptText = [System.IO.File]::ReadAllText($env:AGENT_SCRIPT_PATH, [System.Text.Encoding]::UTF8)
$sb = [ScriptBlock]::Create($scriptText)
$p = @{ ComputerName = $env:AGENT_REMOTE_HOST; ScriptBlock = $sb; ErrorAction = 'Continue' }

if ($env:AGENT_REMOTE_USER) {
    $sec = ConvertTo-SecureString -String $env:AGENT_REMOTE_PASS -AsPlainText -Force
    $p.Credential = [System.Management.Automation.PSCredential]::new($env:AGENT_REMOTE_USER, $sec)
}
Remove-Item Env:AGENT_REMOTE_PASS -ErrorAction SilentlyContinue
if ($env:AGENT_REMOTE_PORT) { $p.Port = [int]$env:AGENT_REMOTE_PORT }
if ($env:AGENT_REMOTE_SSL -eq '1') {
    $p.UseSSL = $true
    $p.SessionOption = New-PSSessionOption -SkipCACheck -SkipCNCheck -SkipRevocationCheck
}
if ($env:AGENT_REMOTE_AUTH) { $p.Authentication = $env:AGENT_REMOTE_AUTH }

$before = $Error.Count
Invoke-Command @p 2>&1 | Out-String -Width 220 -Stream
if ($Error.Count -gt $before) { exit 1 }
exit 0
