import subprocess
rules=[['-d', '169.254.169.254', '-m', 'owner', '--uid-owner', '1002', '-j', 'DROP'], ['-d', '127.0.0.0/8', '-p', 'tcp', '-m', 'conntrack', '--ctstate', 'NEW', '-m', 'multiport', '!', '--dports', '17100,17200,17306,18081,18443', '-m', 'owner', '--uid-owner', '1002', '-j', 'REJECT']]
for rule in rules:
    if subprocess.run(["iptables","-C","OUTPUT",*rule],capture_output=True).returncode:
        subprocess.run(["iptables","-I","OUTPUT",*rule],check=True)
