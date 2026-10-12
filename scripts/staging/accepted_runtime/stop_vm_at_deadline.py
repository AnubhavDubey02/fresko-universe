import datetime,os,subprocess,sys,urllib.request
assert os.geteuid()==0
PROJECT="project-86f9787f-03f9-4f7e-b10"
ZONE="asia-south1-a"
INSTANCE="fresko-staging-vm"
DEADLINE=datetime.datetime(2026,10,17,18,29,tzinfo=datetime.timezone.utc)
def metadata(path):
    request=urllib.request.Request("http://169.254.169.254/computeMetadata/v1/"+path,headers={"Metadata-Flavor":"Google"})
    with urllib.request.urlopen(request,timeout=15) as response:return response.read().decode()
assert metadata("project/project-id")==PROJECT
assert metadata("instance/name")==INSTANCE
assert metadata("instance/zone").endswith("/zones/"+ZONE)
if sys.argv[1:]==["--check"]:
    from pathlib import Path
    assert Path("/usr/sbin/shutdown").exists()
    print("PASS: exact VM identity, root execution and documented guest shutdown command verified; no shutdown issued.")
else:
    assert datetime.datetime.now(datetime.timezone.utc)>=DEADLINE, "VM stop cannot run before approved deadline"
    print("Approved clean guest shutdown requested; persistent disk and IP retained.",flush=True)
    subprocess.run(["/usr/sbin/shutdown","-h","now"],check=True)
