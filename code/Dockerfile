FROM shenlw/jdk:8 as jdk8_builder

FROM shenlw/jdk:11 as jdk11_builder

FROM shenlw/jdk:17 as jdk17_builder

FROM shenlw/jdk:21 as jdk21_builder

FROM shenlw/maven:3-jdk-8 as maven_builder

FROM ubuntu:20.04

# Install runtime OS package dependencies
RUN apt-get update -qq && \
    apt-get install -qq --no-install-recommends build-essential ca-certificates openssl wget curl rsync git openssh-client tar zip unzip sqlite3 fontconfig libfreetype6 iproute2 libstdc++6 && \
    DEBIAN_FRONTEND=noninteractive apt-get -qq --no-install-recommends install tzdata && \
    ln -fs /usr/share/zoneinfo/Asia/Shanghai /etc/localtime && \
    dpkg-reconfigure -f noninteractive tzdata && \
    rm -rf /var/lib/apt/lists/*

# Install java
COPY --from=jdk8_builder /usr/lib/jvm/java-8 /usr/lib/jvm/java-8
COPY --from=jdk11_builder /usr/lib/jvm/java-11 /usr/lib/jvm/java-11
COPY --from=jdk17_builder /usr/lib/jvm/java-17 /usr/lib/jvm/java-17
COPY --from=jdk21_builder /usr/lib/jvm/java-21 /usr/lib/jvm/java-21

ENV JAVA_HOME="/usr/lib/jvm/default-jvm"

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN ln -s "/usr/lib/jvm/java-11" "$JAVA_HOME" && \
    ln -s "$JAVA_HOME/bin/"* "/usr/bin/" && \
    echo "alias j8='rm $JAVA_HOME && ln -s /usr/lib/jvm/java-8 /usr/lib/jvm/default-jvm'" | tee -a "$HOME/.bashrc" && \
    echo "alias j11='rm $JAVA_HOME && ln -s /usr/lib/jvm/java-11 /usr/lib/jvm/default-jvm'" | tee -a "$HOME/.bashrc" && \
    echo "alias j17='rm $JAVA_HOME && ln -s /usr/lib/jvm/java-17 /usr/lib/jvm/default-jvm'" | tee -a "$HOME/.bashrc" && \
    echo "alias j21='rm $JAVA_HOME && ln -s /usr/lib/jvm/java-21 /usr/lib/jvm/default-jvm'" | tee -a "$HOME/.bashrc"

# Install Maven
ENV MAVEN_HOME=/usr/share/maven
ENV MAVEN_CONFIG="$HOME/.m2"

COPY --from=maven_builder $MAVEN_HOME $MAVEN_HOME
COPY --from=maven_builder /usr/local/bin/mvn-entrypoint.sh /usr/local/bin/mvn-entrypoint.sh
COPY --from=maven_builder /root/.m2/settings.xml $MAVEN_CONFIG/settings.xml

RUN ln -s $MAVEN_HOME/bin/mvn /usr/bin/mvn

WORKDIR /workspace
