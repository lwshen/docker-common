#!/bin/bash

# Setup SSH authorized_keys
echo "$SSH_PUBLIC_KEY" > /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys

# Start SSH
/usr/sbin/sshd

# Configure and start ngrok
ngrok config add-authtoken "$NGROK_AUTH_TOKEN"
ngrok tcp 22 --log=stdout > /ngrok.log &

# Keep the script running
tail -f /ngrok.log
