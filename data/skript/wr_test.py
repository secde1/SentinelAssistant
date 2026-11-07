import os,winrm
s=winrm.Session('http://192.168.5.5:5985/wsman',auth=(os.environ['WU'],os.environ['WP']),transport='ntlm')
r=s.run_ps('hostname; (Get-Service Spooler).Status')
print(r.status_code, r.std_out.decode('utf-8','ignore'), r.std_err.decode('utf-8','ignore')[:200])
