#! /bin/sh

# exit if a command fails
set -eux

apt-get update -qq
apt-get install -qq --no-install-recommends openssl aws-cli postgresql-client

# cleanup
rm -rf /var/lib/apt/lists/*
