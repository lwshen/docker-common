#! /bin/sh

# exit if a command fails
set -eux

apt-get update -qq
apt-get install -qq --no-install-recommends openssl postgresql-client unzip

curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip
./aws/install

# cleanup
rm -rf /var/lib/apt/lists/*
