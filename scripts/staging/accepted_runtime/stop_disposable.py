import subprocess
for name in ['freskoqa-staging-web.service', 'freskoqa-staging-worker.service', 'freskoqa-staging-https.service', 'freskoqa-staging-redis-cache.service', 'freskoqa-staging-redis-queue.service', 'freskoqa-staging-mariadb.service']:
    subprocess.run(["systemctl", "stop", name], check=False)
