# postgres-backup-s3

Backup PostgresSQL to S3 (supports periodic backups)

## Usage

Docker:

```sh
$ docker run -e S3_ACCESS_KEY_ID=key -e S3_SECRET_ACCESS_KEY=secret -e S3_BUCKET=my-bucket -e S3_PREFIX=backup -e POSTGRES_DATABASE=dbname -e POSTGRES_USER=user -e POSTGRES_PASSWORD=password -e POSTGRES_HOST=localhost shenlw/postgres-backup-s3
```

## Environment variables

| Variable                      | Default   | Required | Description                                                                                                                       |
| ----------------------------- | --------- | -------- | --------------------------------------------------------------------------------------------------------------------------------- |
| POSTGRES_DATABASE             |           | Y        | Database to back up, or 'all' for all connectable non-template databases                                                          |
| POSTGRES_HOST                 |           | Y        | The PostgreSQL host                                                                                                               |
| POSTGRES_PORT                 | 5432      |          | The PostgreSQL port                                                                                                               |
| POSTGRES_USER                 |           | Y        | The PostgreSQL user                                                                                                               |
| POSTGRES_PASSWORD             |           | Y        | The PostgreSQL password                                                                                                           |
| POSTGRES_EXTRA_OPTS           | `auto`    |          | `all`: retain archive metadata. Single database: `--no-owner --no-acl --no-tablespaces`. Explicit options replace these defaults. |
| POSTGRES_MAINTENANCE_DATABASE | postgres  |          | Existing database used to enumerate databases and export global definitions for `all`.                                            |
| POSTGRES_DUMP_ROLE_PASSWORDS  | false     |          | Include role password hashes in `all` backups. Set to `true` only when restoring source passwords is intended.                    |
| POSTGRES_SOURCE_IMAGE         |           |          | Optional source server image tag or digest to record in the backup metadata.                                                      |
| S3_ACCESS_KEY_ID              |           | Y        | Your AWS access key                                                                                                               |
| S3_SECRET_ACCESS_KEY          |           | Y        | Your AWS secret key                                                                                                               |
| S3_BUCKET                     |           | Y        | Your AWS S3 bucket path                                                                                                           |
| S3_PREFIX                     | backup    |          | Path prefix in your bucket                                                                                                        |
| S3_REGION                     | us-west-1 |          | The AWS S3 bucket region                                                                                                          |
| S3_ENDPOINT                   |           |          | The AWS Endpoint URL, for S3 Compliant APIs such as [minio](https://minio.io)                                                     |
| S3_S3V4                       | no        |          | Set to `yes` to enable AWS Signature Version 4, required for [minio](https://minio.io) servers                                    |
| SCHEDULE                      |           |          | Backup schedule time, see explainatons below                                                                                      |
| ENCRYPTION_PASSWORD           |           |          | Password to encrypt the backup. Can be decrypted using `openssl aes-256-cbc -d -in backup.sql.gz.enc -out backup.sql.gz`          |
| DELETE_OLDER_THAN             |           |          | Delete old backups, see explanation and warning below                                                                             |

### Backup Validation and Environment Metadata

Dumping, compression, encryption and uploading are checked separately. A failure
before upload leaves no new S3 object. Each invocation uses its own temporary
directory; temporary files are removed on success or failure. Credentials are not
printed by shell tracing.

For single-database SQL backups, provide enough temporary disk space for the uncompressed SQL and its compressed
(and, when enabled, encrypted) copies. A full temporary disk fails the backup
before upload.

New `.sql.gz` backups contain a leading SQL comment with a SHA-256 checksum of the
SQL payload, source PostgreSQL versions, per-database extension versions and
schemas, the preload configuration, and the dump client version. Set
`POSTGRES_SOURCE_IMAGE` from your deployment configuration to record the source
server image tag/digest too; it cannot be discovered from PostgreSQL automatically.
Do not change extension versions during a backup. This metadata is not a copy of
the extension binaries or the server's configuration files.

The restore images verify this metadata and extension prerequisites before any
restore SQL or `DROP_PUBLIC` operation. Old backups without the metadata remain
supported, with a warning that source extension versions and payload checksums
cannot be verified. The gzip integrity check still applies to old gzip backups.

Build from the repository root so all three images use the same validation code:

```sh
docker build -f postgres-backup-s3/Dockerfile -t postgres-backup-s3:local .
```

### All-database archive bundles

Keep `POSTGRES_DATABASE=all`. Each connectable non-template database is exported
separately using `pg_dump --format=custom`, then packaged as one `.tar` S3 object:

- `database-000000.dump`, etc.: database schemas, data, ownership, ACLs and tablespace assignments.
- `roles.sql`: cluster role definitions/memberships; password hashes are excluded unless `POSTGRES_DUMP_ROLE_PASSWORDS=true`.
- `tablespaces.sql`: custom tablespace definitions, for optional disaster recovery.
- `manifest.json`: original database names mapped to numbered archives, per-file SHA-256 checksums and source environment metadata.
- `COMPLETE`: checksum of the finalized manifest.

The bundle is uploaded only after every export succeeds. S3 exposes the completed
object atomically; restore rejects incomplete bundles and validates every file's
checksum before connecting to the target. Temporary disk space must accommodate
all archives, the tar bundle and an additional encrypted copy when enabled.
Custom archives are already compressed. Extension binaries, configuration files
and replication setup are not included. Database snapshots are independent; this
is not a synchronized snapshot across databases. Avoid database/extension/role
DDL changes during the backup.

`POSTGRES_EXTRA_OPTS=auto` retains all recovery metadata for `all`. For this mode,
only `--verbose`, `-v`, `--blobs`, `-b` and `--large-objects` are accepted as explicit
extra options. Move the old `--no-owner --no-acl --no-tablespaces` settings to the
restore environment; those flags are now enabled there by default.

### Restore policies

Use either restore image with `POSTGRES_DATABASE=postgres` (an existing maintenance
database, never `all`). For local files, mount the bundle and set
`BACKUP_FILE=/backup/all_TIMESTAMP.tar`; the S3 image selects the latest supported
backup in its prefix. New databases use their original names and creation settings
from the archives. Existing databases should be empty; the restore does not drop them.

| Variable               | Default  | Archive bundle behavior                                                                                                    |
| ---------------------- | -------- | -------------------------------------------------------------------------------------------------------------------------- |
| RESTORE_DATABASE       | unset    | Restore all databases; set an exact source database name to restore only that database.                                    |
| RESTORE_NO_OWNER       | true     | Restore objects under the restoring user instead of source owners.                                                         |
| RESTORE_NO_ACL         | true     | Skip source access grants/revocations.                                                                                     |
| RESTORE_NO_TABLESPACES | true     | Use target default storage instead of source tablespace assignments.                                                       |
| RESTORE_ROLES          | false    | Skip the global role script. Enable to restore new roles and memberships.                                                  |
| RESTORE_EXISTING_ROLES | preserve | When roles are enabled, preserve existing role definitions/passwords. `apply` permits source alterations.                  |
| RESTORE_TABLESPACES    | false    | Skip tablespace definitions. Enable only after preparing source paths on the target; existing definitions are not skipped. |

The same bundle supports a portable restore with the defaults or an ownership/ACL
restore using `RESTORE_ROLES=true RESTORE_NO_OWNER=false RESTORE_NO_ACL=false`.
To restore source storage assignments too, prepare tablespace paths and use
`RESTORE_TABLESPACES=true RESTORE_NO_TABLESPACES=false`. Existing roles can also
be provisioned separately. Named roles referenced by row security policies or other
SQL must exist even when ownership and ACL restoration are disabled. New roles have no password unless password hashes were
explicitly included in the backup. Global scripts apply cluster-wide even when
`RESTORE_DATABASE` selects one database. `DROP_PUBLIC=yes` is rejected for bundles.

To inspect a bundle manually:

```sh
tar -xf all_TIMESTAMP.tar
cat manifest.json
pg_restore --list database-000000.dump
```

### Single-database and legacy SQL backups

A specific `POSTGRES_DATABASE=dbname` keeps the existing `.sql.gz` format. With
`POSTGRES_EXTRA_OPTS=auto`, it retains the previous
`--no-owner --no-acl --no-tablespaces` defaults. Explicit options replace that list.
SQL files already encode their restore behavior; the new archive policy switches
do not apply to them; `RESTORE_DATABASE` is rejected for legacy SQL. Regenerate as an `all` bundle to make
these choices at restore time. Legacy `.sql`, `.sql.gz`, `.zip` and `.sql.gz.enc`
files remain supported by the file restore image; S3 supports the gzip formats.
Legacy all-database SQL restores still create missing roles and preserve existing
roles by default, unlike bundles where role restoration is opt-in.

### Automatic Periodic Backups

The container runs one backup immediately on every start, including restarts.
Without `SCHEDULE`, it exits after that backup. If the initial backup fails, the
container exits with an error before starting the scheduler.

Set the `SCHEDULE` environment variable, for example `-e SCHEDULE="@daily"`, to
continue with periodic backups after the initial backup succeeds.

More information about the scheduling can be found [here](https://pkg.go.dev/github.com/robfig/cron?utm_source=godoc#hdr-Predefined_schedules).

### Delete Old Backups

You can additionally set the `DELETE_OLDER_THAN` environment variable like `-e DELETE_OLDER_THAN="30 days ago"` to delete old backups.

WARNING: this will delete all files in the S3_PREFIX path, not just those created by this script.

### Encryption

You can additionally set the `ENCRYPTION_PASSWORD` environment variable like `-e ENCRYPTION_PASSWORD="superstrongpassword"` to encrypt the backup. Decrypt with `openssl aes-256-cbc -d -in backup.tar.enc -out backup.tar` for bundles, or use the corresponding `.sql.gz` filenames for single-database backups.
