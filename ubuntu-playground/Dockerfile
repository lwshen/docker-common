FROM ubuntu:24.04

# Use Tsinghua University mirror
RUN apt-get update \
  && apt-get install -y --no-install-recommends curl wget ca-certificates iputils-ping telnet \
  && apt-get clean \
  && rm -rf /var/lib/apt/lists/*

COPY ubuntu.sources /etc/apt/sources.list.d/ubuntu.sources
 
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Install NextTrace
RUN curl "https://nxtrace.org/nt" | sed 's/--connect-timeout 1.5/--connect-timeout 10/g' | bash
