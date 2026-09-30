#!/bin/sh
set -eu
python /runner/probe.py
# The server and its installation stay in the same bounded container as the test.
printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d
chmod +x /usr/sbin/policy-rc.d
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install --no-install-recommends -y postgresql-15
python -m pip install --no-deps -r /runner/postgres-dependencies.lock
/usr/lib/postgresql/15/bin/postgres --version > /reports/postgres-version.txt
dpkg-query -W > /reports/system-packages.txt
mkdir /data/postgres
chown postgres:postgres /data/postgres
chmod 1777 /data
runuser -u postgres -- /usr/lib/postgresql/15/bin/initdb -D /data/postgres --auth-local=trust --auth-host=reject
runuser -u postgres -- /usr/lib/postgresql/15/bin/pg_ctl -D /data/postgres -l /data/postgres.log -o "-k /data -c listen_addresses='' -c shared_buffers=64MB -c max_connections=10" start
trap 'runuser -u postgres -- /usr/lib/postgresql/15/bin/pg_ctl -D /data/postgres stop' EXIT
cp /runner/workloads/test_bulk_memory.py /work/tests/test_bulk_memory.py
python -m pip install --no-deps --no-build-isolation -e .
python /runner/check_compiled.py
python /runner/postgres_bulk.py
