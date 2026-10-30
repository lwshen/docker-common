FROM ubuntu:24.04

WORKDIR /app

COPY postgres-restore-s3/install.sh install.sh
RUN sh install.sh && rm install.sh

COPY postgres-common/backup_tools.py backup_tools.py

ENV POSTGRES_DATABASE=**None**
ENV POSTGRES_HOST=**None**
ENV POSTGRES_PORT=5432
ENV POSTGRES_USER=**None**
# Placeholder sentinel, not a secret: restore.sh errors out unless it is overridden at runtime
# hadolint ignore=DL3064
ENV POSTGRES_PASSWORD=**None**
ENV S3_ACCESS_KEY_ID=**None**
# hadolint ignore=DL3064
ENV S3_SECRET_ACCESS_KEY=**None**
ENV S3_BUCKET=**None**
ENV S3_REGION=us-west-1
ENV S3_PREFIX=backup
ENV S3_ENDPOINT=None
# Runtime encryption password sentinel, not a secret.
# hadolint ignore=DL3064
ENV ENCRYPTION_PASSWORD=None
ENV DROP_PUBLIC='no'
ENV RESTORE_EXISTING_ROLES=preserve
ENV RESTORE_ROLES=false
ENV RESTORE_TABLESPACES=false
ENV RESTORE_NO_OWNER=true
ENV RESTORE_NO_ACL=true
ENV RESTORE_NO_TABLESPACES=true
ENV RESTORE_DATABASE=""

COPY postgres-restore-s3/restore.sh restore.sh

CMD ["sh", "restore.sh"]
