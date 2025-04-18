#! /bin/sh

set -eux

if [ "${POSTGRES_DATABASE}" = "**None**" ]; then
  echo "You need to set the POSTGRES_DATABASE environment variable."
  exit 1
fi

if [ "${POSTGRES_HOST}" = "**None**" ]; then
  if [ -n "${POSTGRES_PORT_5432_TCP_ADDR}" ]; then
    POSTGRES_HOST=$POSTGRES_PORT_5432_TCP_ADDR
    POSTGRES_PORT=$POSTGRES_PORT_5432_TCP_PORT
  else
    echo "You need to set the POSTGRES_HOST environment variable."
    exit 1
  fi
fi

if [ "${POSTGRES_USER}" = "**None**" ]; then
  echo "You need to set the POSTGRES_USER environment variable."
  exit 1
fi

if [ "${POSTGRES_PASSWORD}" = "**None**" ]; then
  echo "You need to set the POSTGRES_PASSWORD environment variable or link to a container named POSTGRES."
  exit 1
fi

if [ ! -f "${BACKUP_FILE}" ]; then
  echo "Backup file ${BACKUP_FILE} not found. Mount a volume with your backup file to /backup."
  exit 1
fi

export PGPASSWORD=$POSTGRES_PASSWORD
POSTGRES_HOST_OPTS="-h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER"

echo "Using backup file: ${BACKUP_FILE}"

# Check file extension and decompress if necessary
BACKUP_FILENAME=$(basename "${BACKUP_FILE}")
if [[ "${BACKUP_FILE}" == *.gz ]]; then
  echo "Decompressing gzip backup file"
  cp "${BACKUP_FILE}" /tmp/dump.sql.gz
  gzip -d /tmp/dump.sql.gz
  DUMP_FILE="/tmp/dump.sql"
elif [[ "${BACKUP_FILE}" == *.zip ]]; then
  echo "Decompressing zip backup file"
  apt-get update -qq && apt-get install -qq --no-install-recommends unzip
  unzip -p "${BACKUP_FILE}" > /tmp/dump.sql
  DUMP_FILE="/tmp/dump.sql"
else
  echo "Using backup file as-is"
  DUMP_FILE="${BACKUP_FILE}"
fi

if [ "${DROP_PUBLIC}" == "yes" ]; then
  echo "Recreating the public schema"
  psql $POSTGRES_HOST_OPTS -d $POSTGRES_DATABASE -c "drop schema public cascade; create schema public;"
fi

echo "Restoring database from ${BACKUP_FILENAME}"
psql $POSTGRES_HOST_OPTS -d $POSTGRES_DATABASE < "${DUMP_FILE}"

echo "Restore complete"