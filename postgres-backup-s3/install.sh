#! /bin/sh

# exit if a command fails
set -eux

apt-get update -qq
snap install aws-cli --classic
apt-get install -qq --no-install-recommends openssl postgresql-client

# cleanup
rm -rf /var/lib/apt/lists/*
