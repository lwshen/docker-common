FROM ubuntu:24.04

# Disable interactive prompts
ENV DEBIAN_FRONTEND=noninteractive

# Install necessary packages
RUN apt-get update \
    && apt-get install -y --no-install-recommends python-is-python3 python3-venv python3-pip curl sudo wget htop vim git openssh-server \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Setup SSH
RUN mkdir /var/run/sshd && \
    mkdir -p /root/.ssh && \
    chmod 700 /root/.ssh && \
    echo "PubkeyAuthentication yes\nPasswordAuthentication no\nChallengeResponseAuthentication no\nPermitRootLogin yes" >> /etc/ssh/sshd_config

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Install ngrok
RUN curl -s https://ngrok-agent.s3.amazonaws.com/ngrok.asc | tee /etc/apt/trusted.gpg.d/ngrok.asc >/dev/null && \
    echo "deb https://ngrok-agent.s3.amazonaws.com buster main" | tee /etc/apt/sources.list.d/ngrok.list && \
    apt-get update && apt-get install -y --no-install-recommends ngrok && rm -rf /var/lib/apt/lists/*

EXPOSE 22 8080

# Add entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]