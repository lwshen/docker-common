FROM ubuntu:18.04

ENV JAVA_VERSION=8 \
    JAVA_UPDATE=312 \
    JAVA_BUILD=07 \
    JAVA_HOME="/usr/lib/jvm/default-jvm"

ENV LC_ALL=C.UTF-8
ENV LANG=C.UTF-8

RUN apt-get update
RUN apt-get install -y build-essential
RUN apt-get install -y wget
RUN apt-get install -y rsync

RUN cd /tmp && \
    wget -q --no-check-certificate https://github.com/adoptium/temurin${JAVA_VERSION}-binaries/releases/download/jdk${JAVA_VERSION}u${JAVA_UPDATE}-b${JAVA_BUILD}/OpenJDK${JAVA_VERSION}U-jdk_x64_linux_hotspot_${JAVA_VERSION}u${JAVA_UPDATE}b${JAVA_BUILD}.tar.gz && \
    tar -xzf "OpenJDK${JAVA_VERSION}U-jdk_x64_linux_hotspot_${JAVA_VERSION}u${JAVA_UPDATE}b${JAVA_BUILD}.tar.gz" && \
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

# https://github.com/adoptium/temurin11-binaries/releases/download/jdk-11.0.13%2B8/OpenJDK11U-jdk_x64_linux_hotspot_11.0.13_8.tar.gz

# https://github.com/adoptium/temurin17-binaries/releases/download/jdk-17.0.1%2B12/OpenJDK17U-jdk_x64_linux_hotspot_17.0.1_12.tar.gz