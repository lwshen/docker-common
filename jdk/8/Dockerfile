FROM ubuntu:18.04

ENV JAVA_VERSION=8 \
    JAVA_UPDATE=312 \
    JAVA_BUILD=07 \
    JAVA_HOME="/usr/lib/jvm/default-jvm"

ENV LC_ALL=C.UTF-8
ENV LANG=C.UTF-8

RUN apt-get update -qq && \
    apt-get install -qq --no-install-recommends build-essential ca-certificates wget curl rsync && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /tmp

RUN set -eux; \
    ARCH="$(dpkg --print-architecture)"; \
    case "${ARCH}" in \
       aarch64|arm64) \
         BINARY_URL="https://github.com/adoptium/temurin${JAVA_VERSION}-binaries/releases/download/jdk${JAVA_VERSION}u${JAVA_UPDATE}-b${JAVA_BUILD}/OpenJDK${JAVA_VERSION}U-jdk_aarch64_linux_hotspot_${JAVA_VERSION}u${JAVA_UPDATE}b${JAVA_BUILD}.tar.gz"; \
         ;; \
       armhf|arm) \
         BINARY_URL="https://github.com/adoptium/temurin${JAVA_VERSION}-binaries/releases/download/jdk${JAVA_VERSION}u${JAVA_UPDATE}-b${JAVA_BUILD}/OpenJDK${JAVA_VERSION}U-jdk_arm_linux_hotspot_${JAVA_VERSION}u${JAVA_UPDATE}b${JAVA_BUILD}.tar.gz"; \
         ;; \
       ppc64el|powerpc:common64) \
         BINARY_URL="https://github.com/adoptium/temurin${JAVA_VERSION}-binaries/releases/download/jdk${JAVA_VERSION}u${JAVA_UPDATE}-b${JAVA_BUILD}/OpenJDK${JAVA_VERSION}U-jdk_ppc64le_linux_hotspot_${JAVA_VERSION}u${JAVA_UPDATE}b${JAVA_BUILD}.tar.gz"; \
         ;; \
       amd64|i386:x86-64) \
         BINARY_URL="https://github.com/adoptium/temurin${JAVA_VERSION}-binaries/releases/download/jdk${JAVA_VERSION}u${JAVA_UPDATE}-b${JAVA_BUILD}/OpenJDK${JAVA_VERSION}U-jdk_x64_linux_hotspot_${JAVA_VERSION}u${JAVA_UPDATE}b${JAVA_BUILD}.tar.gz"; \
         ;; \
       *) \
         echo "Unsupported arch: ${ARCH}"; \
         exit 1; \
         ;; \
    esac; \
    wget -q --no-check-certificate ${BINARY_URL} -O openjdk.tar.gz && \
    tar -xzf openjdk.tar.gz && \
    mkdir -p "/usr/lib/jvm" && \
    mv "/tmp/jdk${JAVA_VERSION}u${JAVA_UPDATE}-b"${JAVA_BUILD} "/usr/lib/jvm/java-${JAVA_VERSION}" && \
    ln -s "java-${JAVA_VERSION}" "$JAVA_HOME" && \
    ln -s "$JAVA_HOME/bin/"* "/usr/bin/" && \
    rm "/tmp/"* && \
    \
    echo 'public class Main { public static void main(String[] args) { System.out.println("Java code is running fine!"); } }' > Main.java && \
    javac Main.java && \
    java Main && \
    rm -r "/tmp/"*
