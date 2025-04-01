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

# Install cpolar
RUN set -eux; \
    ARCH="$(dpkg --print-architecture)"; \
    case "${ARCH}" in \
       aarch64|arm64) \
         BINARY_URL="https://www.cpolar.com/static/downloads/releases/3.3.18/cpolar-stable-linux-arm.zip"; \
         ;; \
       amd64|i386:x86-64) \
         BINARY_URL="https://www.cpolar.com/static/downloads/releases/3.3.18/cpolar-stable-linux-amd64.zip"; \
         ;; \
       *) \
         echo "Unsupported arch: ${ARCH}"; \
         exit 1; \
         ;; \
    esac; \
    wget -q --no-check-certificate ${BINARY_URL} -O cpolar.zip && \
    unzip cpolar.zip && \
    rm cpolar.zip && \
    chmod +x cpolar && \
    mv cpolar /usr/local/bin/cpolar

EXPOSE 22 8080

# Add entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]