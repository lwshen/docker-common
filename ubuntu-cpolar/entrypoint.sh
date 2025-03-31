#!/bin/bash

# Setup SSH authorized_keys
echo "$SSH_PUBLIC_KEY" > /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys

# Start SSH
/usr/sbin/sshd

# Configure and start cpolar
cpolar authtoken "$CPOLAR_AUTH_TOKEN"
CPOLAR_REGION=${CPOLAR_REGION:-us}
cpolar tcp 22 -region="$CPOLAR_REGION" -log=stdout > /cpolar.log &

# Keep the script running
tail -f /cpolar.log
