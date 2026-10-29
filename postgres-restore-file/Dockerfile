FROM ubuntu:24.04

WORKDIR /app

COPY postgres-restore-file/install.sh install.sh
RUN sh install.sh && rm install.sh

COPY postgres-common/backup_tools.py backup_tools.py

ENV POSTGRES_DATABASE=**None**
ENV POSTGRES_HOST=**None**
ENV POSTGRES_PORT=5432
ENV POSTGRES_USER=**None**
# Placeholder sentinel, not a secret: restore.sh errors out unless it is overridden at runtime
# hadolint ignore=DL3064
ENV POSTGRES_PASSWORD=**None**
ENV BACKUP_FILE="/backup/dump.sql"
ENV DROP_PUBLIC='no'
ENV RESTORE_EXISTING_ROLES=preserve

COPY postgres-restore-file/restore.sh restore.sh

# Create a volume for the backup file
VOLUME /backup

CMD ["sh", "restore.sh"]