#! /bin/sh

# exit if a command fails
set -eux

apt-get update -qq
apt-get install -qq --no-install-recommends ca-certificates openssl unzip curl postgresql-common

# Add official PostgreSQL apt repository to not depend on Debian's version.
#   https://www.postgresql.org/download/linux/debian/
/usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y
apt-get install -qq --no-install-recommends postgresql-client-17

if [ "$(uname -m)" = "x86_64" ]; then
    curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
elif [ "$(uname -m)" = "aarch64" ]; then
    curl "https://awscli.amazonaws.com/awscli-exe-linux-aarch64.zip" -o "awscliv2.zip"
else
    echo "Unsupported architecture: $(uname -m)"
    exit 1
fi
unzip awscliv2.zip
./aws/install

# cleanup
rm -rf /var/lib/apt/lists/*
