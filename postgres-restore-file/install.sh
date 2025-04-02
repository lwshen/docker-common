#! /bin/sh

# exit if a command fails
set -eux

apt-get update -qq
apt-get install -qq --no-install-recommends ca-certificates openssl curl postgresql-common

# Add official PostgreSQL apt repository
/usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y
apt-get install -qq --no-install-recommends postgresql-client-17

# cleanup
rm -rf /var/lib/apt/lists/*