FROM ubuntu:24.04

WORKDIR /app

COPY install.sh install.sh
RUN sh install.sh && rm install.sh

ENV POSTGRES_DATABASE=**None**
ENV POSTGRES_HOST=**None**
ENV POSTGRES_PORT=5432
ENV POSTGRES_USER=**None**
ENV POSTGRES_PASSWORD=**None**
ENV BACKUP_FILE="/backup/dump.sql"
ENV DROP_PUBLIC='no'

COPY restore.sh restore.sh

# Create a volume for the backup file
VOLUME /backup

CMD ["sh", "restore.sh"]