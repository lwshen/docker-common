# Postgres Restore from File

This image restores a PostgreSQL database from a local backup file.

## Usage

```bash
docker run -d \
  -e POSTGRES_DATABASE=dbname \
  -e POSTGRES_HOST=postgres \
  -e POSTGRES_PORT=5432 \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=password \
  -e BACKUP_FILE=/backup/dump.sql.gz \
  -e DROP_PUBLIC=no \
  -v /path/to/your/backups:/backup \
  shenlw/postgres-restore-file
```

## Environment Variables

- `POSTGRES_DATABASE`: The database name to restore to
- `POSTGRES_HOST`: The PostgreSQL server host
- `POSTGRES_PORT`: The PostgreSQL server port (default: 5432)
- `POSTGRES_USER`: The PostgreSQL username
- `POSTGRES_PASSWORD`: The PostgreSQL password
- `BACKUP_FILE`: Path to the backup file inside the container (default: /backup/dump.sql.gz)
- `DROP_PUBLIC`: Whether to drop and recreate the public schema (yes/no, default: no)

## Backup File Format

The backup file can be:
- A plain SQL dump file (.sql)
- A gzipped SQL dump file (.sql.gz)
- A zipped SQL dump file (.zip)

## Example

```bash
# Restore the most recent dump file to a local Postgres database
docker run --rm \
  -e POSTGRES_DATABASE=my_database \
  -e POSTGRES_HOST=host.docker.internal \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=password \
  -e BACKUP_FILE=/backup/my_dump.sql.gz \
  -v /path/to/backups:/backup \
  shenlw/postgres-restore-file
```