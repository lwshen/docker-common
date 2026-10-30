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
- `BACKUP_FILE`: Path to the backup file inside the container (default: /backup/dump.sql)
- `DROP_PUBLIC`: Whether to drop and recreate the public schema (yes/no, default: no)
- `ENCRYPTION_PASSWORD`: Required for `.sql.gz.enc` or `.tar.gz.enc` files, if encrypted.
- `RESTORE_EXISTING_ROLES`: `preserve` (default) keeps existing target role definitions/passwords; `apply` applies source role alterations. Duplicate role creation is skipped in either mode. New roles and memberships are restored for legacy SQL, or when `RESTORE_ROLES=true` for bundles.

## Backup File Format

The backup file can be:

- A plain SQL dump file (.sql)
- A gzipped SQL dump file (.sql.gz)
- A zipped SQL dump containing exactly one file (.zip)
- An encrypted gzip SQL dump (.sql.gz.enc)
- An all-database SQL bundle (.tar.gz), optionally encrypted (.tar.gz.enc)

## All-database SQL bundles

New `POSTGRES_DATABASE=all` backups are `.tar.gz` bundles. Each database is a
plain SQL file named after the database (`databases/app.sql`), next to separate
global scripts, checksums and a completion marker. Bundles from the previous
`.tar` format are rejected. All files are validated before the target is changed.
Use an existing maintenance database such as `POSTGRES_DATABASE=postgres`.
Databases restore to their original names; existing databases should be empty
and keep their own database-level settings.

| Variable               | Default  | Description                                                                                      |
| ---------------------- | -------- | ------------------------------------------------------------------------------------------------ |
| RESTORE_DATABASE       | unset    | Exact source database name to restore; unset restores every database.                            |
| RESTORE_ROLES          | false    | Apply the separate role script, including new roles and memberships.                             |
| RESTORE_EXISTING_ROLES | preserve | Preserve existing role attributes/passwords; `apply` permits alterations when roles are enabled. |
| RESTORE_TABLESPACES    | false    | Apply tablespace definitions; prepare paths first and avoid existing name conflicts.             |

For example, use `RESTORE_DATABASE=app` to restore only `app`. Bundles are dumped
without ownership, grants or tablespace assignments, so restored objects belong
to the restoring user. Role/tablespace scripts are cluster-wide even for a
selected database. Named roles referenced by policies or other SQL must already
exist, or enable `RESTORE_ROLES`. Password hashes are included only if the backup
used `POSTGRES_DUMP_ROLE_PASSWORDS=true`. `DROP_PUBLIC=yes` is rejected for
bundles. Each database is loaded with `psql -X -v ON_ERROR_STOP=1`; earlier
changes may remain after a failure.

To restore one database by hand instead, extract its file and run it with a
recent `psql`:

```sh
tar -xzf all_TIMESTAMP.tar.gz databases/app.sql
psql -d postgres -f databases/app.sql
```

These switches apply to bundles. Legacy SQL restore behavior is already encoded
in its statements: missing roles/memberships are restored and existing roles are
preserved by default. Bundle switches do not apply to legacy SQL files; `RESTORE_DATABASE` is rejected
for these files. See [backup formats](../postgres-backup-s3/README.md) for details.

## Restore validation

New backups contain embedded PostgreSQL/extension metadata and an SQL payload
checksum. Validation runs before restore SQL or `DROP_PUBLIC`: it checks integrity,
the server major version, extension availability/versions/dependency order and
recorded extension preloads. Use the same or a newer server major and matching extension packages.
For old SQL/gzip/ZIP files, source extension versions and payload checksums are
unavailable; declared extension dependencies and compressed-file integrity are
still checked. The checks do not install or enable extensions automatically.

Unexpected SQL errors stop `psql` and return a nonzero exit status. A success
message is printed only after the complete SQL file executes. Earlier changes may
already be committed, so retry failed restores on a clean target. `DROP_PUBLIC=yes`
is rejected for dumps that switch databases.

All-database backups should initially connect to an existing maintenance database
such as `postgres`, using a superuser. Existing target role definitions/passwords
are preserved by default, while new roles and role memberships are restored for legacy SQL.

Build from the repository root to include the shared validation helper:

```sh
docker build -f postgres-restore-file/Dockerfile -t postgres-restore-file:local .
```

`RESTORE_ALLOW_EXTENSION_VERSION_MISMATCH=false` is the default. Set it to `true`
for an explicitly reviewed extension migration; it permits version differences
while retaining availability and dependency checks. PostgreSQL upgrades to newer
majors are allowed; downgrades are rejected. Preload metadata unavailable to the
connected role is reported as unknown and its preload comparison is skipped.

Bundle restores create databases using target default storage. Database-specific
`ALTER ROLE ... IN DATABASE ... SET` settings are applied only to databases created
by the restore, and only with `RESTORE_ROLES=true`.

Plain SQL restore needs one uncompressed temporary SQL file, plus the downloaded
or mounted source and, if encrypted, its decrypted compressed copy. Role filtering
compacts the temporary SQL in place; metadata collection and filtering share one
SQL scan. Source SQL bytes are preserved without UTF-8 transcoding. Bundle
restores extract every SQL file uncompressed before validation, so provide space
for the whole uncompressed bundle.
