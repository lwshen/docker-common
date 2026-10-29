# postgres-restore-s3

Restore a SQL backup from S3 to PostgresSQL

## Warning

This will potentially put your database in a very bad state or complete destroy your data, be very careful.

## Limitations

This is made to restore a backup made from postgres-backup-s3, if you backup came from somewhere else please check your format.

- The S3 prefix must contain only backups you intend to restore. The newest `.tar`, `.tar.enc`, `.sql.gz` or `.sql.gz.enc` object is selected by modification time (with the key as a tie-breaker).
- S3 object listing is paginated automatically by the AWS CLI.
- Backups are archive bundles or gzip-compressed SQL, optionally encrypted with the existing OpenSSL format.

## Archive bundles and restore policies

New `POSTGRES_DATABASE=all` backups are `.tar` bundles containing a custom archive
for each database, separate global scripts, checksums and a completion marker.
All files are validated before the target is changed. Use an existing maintenance
database such as `POSTGRES_DATABASE=postgres`. Databases restore to their original
names; existing databases should be empty.

| Variable               | Default  | Description                                                                                      |
| ---------------------- | -------- | ------------------------------------------------------------------------------------------------ |
| RESTORE_DATABASE       | unset    | Exact source database name to restore; unset restores every database.                            |
| RESTORE_NO_OWNER       | true     | Skip source ownership.                                                                           |
| RESTORE_NO_ACL         | true     | Skip source grants/revocations.                                                                  |
| RESTORE_NO_TABLESPACES | true     | Skip source storage assignments.                                                                 |
| RESTORE_ROLES          | false    | Apply the separate role script, including new roles and memberships.                             |
| RESTORE_EXISTING_ROLES | preserve | Preserve existing role attributes/passwords; `apply` permits alterations when roles are enabled. |
| RESTORE_TABLESPACES    | false    | Apply tablespace definitions; prepare paths first and avoid existing name conflicts.             |

For example, use `RESTORE_DATABASE=app` to restore only `app`. To retain ownership
and grants from the same backup, also use `RESTORE_ROLES=true`,
`RESTORE_NO_OWNER=false` and `RESTORE_NO_ACL=false`. For source storage assignments,
prepare target paths and use `RESTORE_TABLESPACES=true RESTORE_NO_TABLESPACES=false`.
Role/tablespace scripts are cluster-wide even for a selected database. Named roles
referenced by policies or other SQL must already exist, or enable `RESTORE_ROLES`. Password
hashes are included only if the backup used `POSTGRES_DUMP_ROLE_PASSWORDS=true`.
`DROP_PUBLIC=yes` is rejected for bundles. Archive restore uses
`pg_restore --exit-on-error`; earlier changes may remain after a failure.

These switches apply to bundles. Legacy SQL restore behavior is already encoded
in its statements: missing roles/memberships are restored and existing roles are
preserved by default. Archive filters do not apply to legacy SQL files; `RESTORE_DATABASE` is rejected
for these files. See [backup formats](../postgres-backup-s3/README.md) for details.

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

For legacy SQL, `RESTORE_EXISTING_ROLES=preserve` skips top-level `CREATE ROLE` and
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
