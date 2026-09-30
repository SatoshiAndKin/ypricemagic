"""Exercise the real BuildKit interruption path with a small sleeping build."""
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

root = Path('/Users/bryan/code/ypricemagic')
base = Path('/private/tmp/yprice-memory/build-interruption-final')
context = 'colima-ypricemagic'
builder = 'ypricemagic-validation-' + hashlib.sha256(context.encode()).hexdigest()[:12]
os.environ['DOCKER_CONTEXT'] = context
sys.path.insert(0, str(root/'tools/validation'))
import run
run.BUILDER = builder

if len(sys.argv)>1:
    def stop(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    try:
        run.build(base/'source',base/'report','3.12',base/'harness')
    except KeyboardInterrupt:
        raise SystemExit(130)
    raise AssertionError('Sleeping build finished before cancellation')

base.mkdir()
for name in ('source','report','harness'):
    (base/name).mkdir()
for name in ('requirements.txt','requirements-dev.txt'):
    (base/'source'/name).write_text('')
(base/'source/pyproject.toml').write_text('[build-system]\nrequires=[]\n')
marker = 'yprice-build-interruption-' + str(time.time_ns())
# BusyBox was already used for the validation lock. Keep this fixture small.
(base/'harness/Dockerfile').write_text('FROM busybox:1.37.0\nRUN echo '+marker+' && sleep 3600\n')
(base/'runner-sha256.json').write_text(json.dumps({name:hashlib.sha256((root/'tools/validation'/name).read_bytes()).hexdigest() for name in ('run.py','common.py')},indent=2)+'\n')
run.docker('create','--name',run.LOCK,'--label','ypricemagic.validation=lock','busybox:latest','true')
child = None
started = time.monotonic()
try:
    child = subprocess.Popen([sys.executable,__file__,'worker'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    log=base/'report/build.log'
    while not log.exists() or (marker+'\n') not in log.read_text():
        if child.poll() is not None:
            raise AssertionError('Build fixture exited before readiness: '+str(child.returncode))
        if time.monotonic()-started>180:
            raise AssertionError('Build fixture did not reach its sleeping step')
        time.sleep(.25)
    child.send_signal(signal.SIGTERM)
    assert child.wait(timeout=60)==130
    record=json.loads((base/'report/build-status.json').read_text())
    assert record['exit_code'] is None and not record['state']['OOMKilled'],record
    assert 0 < record['cgroup']['peak_bytes'] < 7*1024**3,record
    assert all(int(record['cgroup']['events'][key])==0 for key in ('oom','oom_kill')),record
    limits=json.loads((base/'report/builder-limits.json').read_text())['HostConfig']
    assert limits=={'Memory':8*1024**3,'MemorySwap':8*1024**3,'CpuPeriod':100000,'CpuQuota':400000,'PidsLimit':512},limits
    state=json.loads(run.docker('inspect','buildx_buildkit_'+builder+'0'))[0]['State']
    assert not state['Running'],state
    result={'complete':True,'fixture_exit_code':child.returncode,'interrupted_build_complete':False,'builder_stopped':True,'evidence_persisted':True,'peak_bytes':record['cgroup']['peak_bytes'],'elapsed_seconds':time.monotonic()-started,'limits':limits}
    (base/'verification.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result),flush=True)
finally:
    if child is not None and child.poll() is None:
        child.send_signal(signal.SIGTERM)
        child.wait(timeout=60)
    run.docker('rm',run.LOCK)
