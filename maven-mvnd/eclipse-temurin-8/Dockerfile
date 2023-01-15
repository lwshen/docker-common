FROM shenlw/jdk:8

ARG MVND_VERSION=0.8.0
ARG USER_HOME_DIR="/root"

RUN apt-get update -qq \
    && apt-get install -qq --no-install-recommends unzip \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL -o /tmp/mvnd.zip https://github.com/apache/maven-mvnd/releases/download/${MVND_VERSION}/mvnd-${MVND_VERSION}-linux-amd64.zip \
    && unzip /tmp/mvnd.zip -d /tmp  \
    && mv /tmp/mvnd-${MVND_VERSION}-linux-amd64 /usr/share/mvnd \
    && rm -f /tmp/mvnd.zip \
    && ln -s /usr/share/mvnd/bin/* /usr/bin/

ENV MAVEN_CONFIG "$USER_HOME_DIR/.m2"

COPY settings-docker.xml $MAVEN_CONFIG/settings.xml

WORKDIR /workspace

CMD ["mvnd"]