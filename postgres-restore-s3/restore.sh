#! /bin/sh

set -eux

if [ "${S3_ACCESS_KEY_ID}" = "**None**" ]; then
  echo "You need to set the S3_ACCESS_KEY_ID environment variable."
  exit 1
fi

if [ "${S3_SECRET_ACCESS_KEY}" = "**None**" ]; then
  echo "You need to set the S3_SECRET_ACCESS_KEY environment variable."
  exit 1
fi

if [ "${S3_BUCKET}" = "**None**" ]; then
  echo "You need to set the S3_BUCKET environment variable."
  exit 1
fi

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

if [ "${S3_ENDPOINT}" = "None" ]; then
  AWS_ARGS=""
else
  AWS_ARGS="--endpoint-url ${S3_ENDPOINT}"
fi

# env vars needed for aws tools
export AWS_ACCESS_KEY_ID=$S3_ACCESS_KEY_ID
export AWS_SECRET_ACCESS_KEY=$S3_SECRET_ACCESS_KEY
export AWS_DEFAULT_REGION=$S3_REGION

export PGPASSWORD=$POSTGRES_PASSWORD
POSTGRES_HOST_OPTS="-h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER"

echo "Finding latest backup"

# First, try to find date folders (format: YYYYMMDD)
DATE_FOLDERS=$(aws $AWS_ARGS s3 ls s3://$S3_BUCKET/$S3_PREFIX/ | grep "PRE " | awk '{ print $2 }' | sed 's/\///g' | grep '^[0-9]\{8\}$' | sort -r)

if [ -n "$DATE_FOLDERS" ]; then
    # If date folders exist, find the latest backup in the most recent date folder
    echo "Found date-specific folders, searching for latest backup"
    for DATE_FOLDER in $DATE_FOLDERS; do
        LATEST_BACKUP=$(aws $AWS_ARGS s3 ls s3://$S3_BUCKET/$S3_PREFIX/$DATE_FOLDER/ | sort | tail -n 1 | awk '{ print $4 }')
        if [ -n "$LATEST_BACKUP" ]; then
            BACKUP_PATH="$S3_PREFIX/$DATE_FOLDER/$LATEST_BACKUP"
            break
        fi
    done
else
    # If no date folders, look directly in the prefix folder (legacy behavior)
    echo "No date folders found, searching in root prefix"
    LATEST_BACKUP=$(aws $AWS_ARGS s3 ls s3://$S3_BUCKET/$S3_PREFIX/ | grep -v "PRE " | sort | tail -n 1 | awk '{ print $4 }')
    BACKUP_PATH="$S3_PREFIX/$LATEST_BACKUP"
fi

if [ -z "$LATEST_BACKUP" ]; then
    echo "No backup files found"
    exit 1
fi

echo "Fetching ${LATEST_BACKUP} from S3 (path: ${BACKUP_PATH})"

# Download the file with its original name
aws $AWS_ARGS s3 cp s3://$S3_BUCKET/$BACKUP_PATH .

# Check if the file is encrypted (ends with .enc)
if echo "${LATEST_BACKUP}" | grep -q '\.enc$'; then
    if [ "${ENCRYPTION_PASSWORD}" = "**None**" ]; then
        echo "Error: Encrypted file found but ENCRYPTION_PASSWORD is not set"
        exit 1
    fi
    echo "Decrypting backup file"
    openssl enc -d -aes-256-cbc -in "${LATEST_BACKUP}" -out dump.sql.gz -k "${ENCRYPTION_PASSWORD}"
    rm "${LATEST_BACKUP}"
else
    # If not encrypted, just rename it
    mv "${LATEST_BACKUP}" dump.sql.gz
fi

gzip -d dump.sql.gz

if [ "${DROP_PUBLIC}" == "yes" ]; then
	echo "Recreating the public schema"
	psql $POSTGRES_HOST_OPTS -d $POSTGRES_DATABASE -c "drop schema public cascade; create schema public;"
fi

echo "Restoring ${LATEST_BACKUP}"

psql $POSTGRES_HOST_OPTS -d $POSTGRES_DATABASE < dump.sql

echo "Restore complete"
