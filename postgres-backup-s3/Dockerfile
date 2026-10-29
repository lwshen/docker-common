FROM golang:1.23-alpine3.21 AS build

WORKDIR /app

COPY postgres-backup-s3/main.go /app/main.go

RUN go mod init github.com/itbm/postgresql-backup-s3 \
	&& go get github.com/robfig/cron/v3@v3.0.1 \
	&& go build -o out/go-cron

FROM ubuntu:24.04

WORKDIR /app

COPY --from=build /app/out/go-cron /usr/local/bin/go-cron

COPY postgres-backup-s3/install.sh install.sh
RUN sh install.sh && rm install.sh

COPY postgres-common/backup_tools.py backup_tools.py

ENV POSTGRES_DATABASE=None
ENV POSTGRES_HOST=None
ENV POSTGRES_PORT=5432
ENV POSTGRES_USER=None
# Placeholder sentinel, not a secret: backup.sh errors out unless it is overridden at runtime
# hadolint ignore=DL3064
ENV POSTGRES_PASSWORD=None
ENV POSTGRES_EXTRA_OPTS='--no-owner --no-acl --no-tablespaces'
# Boolean export policy, not a password or secret.
# hadolint ignore=DL3064
ENV POSTGRES_DUMP_ROLE_PASSWORDS=false
ENV S3_ACCESS_KEY_ID=None
# hadolint ignore=DL3064
ENV S3_SECRET_ACCESS_KEY=None
ENV S3_BUCKET=None
ENV S3_REGION=us-west-1
ENV S3_PREFIX=backup
ENV S3_ENDPOINT=None
ENV S3_S3V4=no
ENV SCHEDULE=None
# hadolint ignore=DL3064
ENV ENCRYPTION_PASSWORD=None
ENV DELETE_OLDER_THAN=None

COPY postgres-backup-s3/run.sh run.sh
COPY postgres-backup-s3/backup.sh backup.sh

ENTRYPOINT []
CMD ["sh", "run.sh"]
