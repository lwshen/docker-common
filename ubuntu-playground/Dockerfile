FROM ubuntu:24.04

# Use Tsinghua University mirror
RUN sed -i 's/archive.ubuntu.com/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list.d/ubuntu.sources \
  && sed -i 's/ports.ubuntu.com/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list.d/ubuntu.sources
RUN apt-get update && apt-get install -y curl

# Install NextTrace
RUN curl https://nxtrace.org/nt | bash
