# Veeam serveri holati: xizmatlar, oxirgi backup natijalari, disklar.
# Ishlatish: run_powershell(host="srv-veeam", script=<shu fayl matni>) — login/parol inventardan avtomatik olinadi.
# Skriptga parol YOZILMAYDI.
Get-Date
Get-Service Veeam* | Select-Object Name, Status | Format-Table -AutoSize | Out-String
try {
    Add-PSSnapin VeeamPSSnapin -ErrorAction SilentlyContinue
    Import-Module Veeam.Backup.PowerShell -ErrorAction SilentlyContinue
    Get-VBRJob | ForEach-Object {
        $l = $_.FindLastSession()
        [pscustomobject]@{ Job = $_.Name; Enabled = $_.IsScheduleEnabled; Result = $l.Result; State = $l.State; End = $l.EndTime }
    } | Format-Table -AutoSize | Out-String -Width 200
} catch { 'VBR xato: ' + $_.Exception.Message }
Get-PSDrive -PSProvider FileSystem |
    Select-Object Name, @{n = 'FreeGB'; e = { [int]($_.Free / 1GB) } }, @{n = 'UsedGB'; e = { [int]($_.Used / 1GB) } } |
    Format-Table -AutoSize | Out-String
