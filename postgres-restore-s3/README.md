# postgres-restore-s3

Restore a SQL backup from S3 to PostgresSQL

## Warning

This will potentially put your database in a very bad state or complete destroy your data, be very careful.

## Limitations

This is made to restore a backup made from postgres-backup-s3, if you backup came from somewhere else please check your format.

- The S3 prefix must contain only backups you intend to restore. The newest `.sql.gz` or `.sql.gz.enc` object is selected by modification time (with the key as a tie-breaker).
- S3 object listing is paginated automatically by the AWS CLI.
- Backups are gzip-compressed SQL, optionally encrypted with the existing OpenSSL format.

## Restore validation

The same validation logic is used by the S3 and local-file images. New backups
carry embedded environment metadata and a SHA-256 checksum. Before changing the
target, the restore checks the checksum, PostgreSQL major version, the versions
and availability of extensions created by the dump, their dependency order, and
extension preload libraries recorded by the source. Use a target with matching
server and extension packages. Checks do not install packages, enable extensions,
or replace a full restore rehearsal.

For existing target databases, an already-enabled matching extension takes
precedence over the server's default extension version. For databases that the
dump will create, the target default extension version must match the source.
Legacy backups are checked for declared extension availability/dependencies, but
cannot provide source extension versions or payload checksum verification.

SQL runs with `psql -X -v ON_ERROR_STOP=1`. Unexpected errors return failure and do
not print `Restore complete`; changes committed before an SQL error are not rolled
back across the entire dump. Start with a clean target when retrying a failed restore.

By default `RESTORE_EXISTING_ROLES=preserve` skips top-level `CREATE ROLE` and
`ALTER ROLE` statements for roles already on the target, preserving their existing
passwords and attributes. New roles and role memberships from the dump are still
restored. Set `RESTORE_EXISTING_ROLES=apply` to apply source `ALTER ROLE` statements
to existing roles too; this can replace passwords if the backup contains them.

For all-database backups, connect initially to an existing maintenance database
with `POSTGRES_DATABASE=postgres`, using a superuser. Keep `DROP_PUBLIC=no`.

Build from the repository root:

```sh
docker build -f postgres-restore-s3/Dockerfile -t postgres-restore-s3:local .
```

## Usage

Docker:

```sh
$ docker run -e S3_ACCESS_KEY_ID=key -e S3_SECRET_ACCESS_KEY=secret -e S3_BUCKET=my-bucket -e S3_PREFIX=backup -e S3_ENDPOINT=endpoint -e S3_REGION=auto -e POSTGRES_USER=user -e POSTGRES_PASSWORD=password -e POSTGRES_HOST=postgres -e POSTGRES_DATABASE=dbname -e ENCRYPTION_PASSWORD=password shenlw/postgres-restore-s3
```

## Dropping public

If you wish to drop the public schema (drop schema public cascade; create schema public) then set the environment variable DROP_PUBLIC=yes. This is useful for situations where you wish to restore a database which currently has data / schemas in it.

This operation runs only after preflight succeeds and is rejected for dumps that
switch between databases.
