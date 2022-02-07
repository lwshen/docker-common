FROM ubuntu:18.04

ENV JAVA_VERSION=17 \
    JAVA_UPDATE=17.0.1 \
    JAVA_BUILD=12 \
    JAVA_HOME="/usr/lib/jvm/default-jvm"

ENV LC_ALL=C.UTF-8
ENV LANG=C.UTF-8

RUN apt-get update -qq && \
    apt-get install -qq --no-install-recommends build-essential ca-certificates wget curl rsync git openssh-client && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /tmp

RUN set -eux; \
    ARCH="$(dpkg --print-architecture)"; \
    case "${ARCH}" in \
       aarch64|arm64) \
         BINARY_URL="https://github.com/adoptium/temurin${JAVA_VERSION}-binaries/releases/download/jdk-${JAVA_UPDATE}%2B${JAVA_BUILD}/OpenJDK${JAVA_VERSION}U-jdk_aarch64_linux_hotspot_${JAVA_UPDATE}_${JAVA_BUILD}.tar.gz"; \
         ;; \
       armhf|arm) \
         BINARY_URL="https://github.com/adoptium/temurin${JAVA_VERSION}-binaries/releases/download/jdk-${JAVA_UPDATE}%2B${JAVA_BUILD}/OpenJDK${JAVA_VERSION}U-jdk_arm_linux_hotspot_${JAVA_UPDATE}_${JAVA_BUILD}.tar.gz"; \
         ;; \
       ppc64el|powerpc:common64) \
         BINARY_URL="https://github.com/adoptium/temurin${JAVA_VERSION}-binaries/releases/download/jdk-${JAVA_UPDATE}%2B${JAVA_BUILD}/OpenJDK${JAVA_VERSION}U-jdk_ppc64le_linux_hotspot_${JAVA_UPDATE}_${JAVA_BUILD}.tar.gz"; \
         ;; \
       s390x|s390:64-bit) \
         BINARY_URL="https://github.com/adoptium/temurin${JAVA_VERSION}-binaries/releases/download/jdk-${JAVA_UPDATE}%2B${JAVA_BUILD}/OpenJDK${JAVA_VERSION}U-jdk_s390x_linux_hotspot_${JAVA_UPDATE}_${JAVA_BUILD}.tar.gz"; \
         ;; \
       amd64|i386:x86-64) \
         BINARY_URL="https://github.com/adoptium/temurin${JAVA_VERSION}-binaries/releases/download/jdk-${JAVA_UPDATE}%2B${JAVA_BUILD}/OpenJDK${JAVA_VERSION}U-jdk_x64_linux_hotspot_${JAVA_UPDATE}_${JAVA_BUILD}.tar.gz"; \
         ;; \
       *) \
         echo "Unsupported arch: ${ARCH}"; \
         exit 1; \
         ;; \
    esac; \
    wget -q --no-check-certificate ${BINARY_URL} -O openjdk.tar.gz && \
    tar -xzf openjdk.tar.gz && \
    mkdir -p "/usr/lib/jvm" && \
    mv "/tmp/jdk-${JAVA_UPDATE}+"${JAVA_BUILD} "/usr/lib/jvm/java-${JAVA_VERSION}" && \
    ln -s "java-${JAVA_VERSION}" "$JAVA_HOME" && \
    ln -s "$JAVA_HOME/bin/"* "/usr/bin/" && \
    rm "/tmp/"*
