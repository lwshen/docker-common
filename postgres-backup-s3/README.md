# postgres-backup-s3

Backup PostgresSQL to S3 (supports periodic backups)

## Usage

Docker:

```sh
$ docker run -e S3_ACCESS_KEY_ID=key -e S3_SECRET_ACCESS_KEY=secret -e S3_BUCKET=my-bucket -e S3_PREFIX=backup -e POSTGRES_DATABASE=dbname -e POSTGRES_USER=user -e POSTGRES_PASSWORD=password -e POSTGRES_HOST=localhost shenlw/postgres-backup-s3
```

## Environment variables

| Variable                     | Default                                | Required | Description                                                                                                              |
| ---------------------------- | -------------------------------------- | -------- | ------------------------------------------------------------------------------------------------------------------------ |
| POSTGRES_DATABASE            |                                        | Y        | Database you want to backup or 'all' to backup everything                                                                |
| POSTGRES_HOST                |                                        | Y        | The PostgreSQL host                                                                                                      |
| POSTGRES_PORT                | 5432                                   |          | The PostgreSQL port                                                                                                      |
| POSTGRES_USER                |                                        | Y        | The PostgreSQL user                                                                                                      |
| POSTGRES_PASSWORD            |                                        | Y        | The PostgreSQL password                                                                                                  |
| POSTGRES_EXTRA_OPTS          | `--no-owner --no-acl --no-tablespaces` |          | Options passed to `pg_dump` / `pg_dumpall`. Setting this variable replaces the defaults.                                 |
| POSTGRES_DUMP_ROLE_PASSWORDS | false                                  |          | Include role password hashes in `all` backups. Set to `true` only when restoring source passwords is intended.           |
| S3_ACCESS_KEY_ID             |                                        | Y        | Your AWS access key                                                                                                      |
| S3_SECRET_ACCESS_KEY         |                                        | Y        | Your AWS secret key                                                                                                      |
| S3_BUCKET                    |                                        | Y        | Your AWS S3 bucket path                                                                                                  |
| S3_PREFIX                    | backup                                 |          | Path prefix in your bucket                                                                                               |
| S3_REGION                    | us-west-1                              |          | The AWS S3 bucket region                                                                                                 |
| S3_ENDPOINT                  |                                        |          | The AWS Endpoint URL, for S3 Compliant APIs such as [minio](https://minio.io)                                            |
| S3_S3V4                      | no                                     |          | Set to `yes` to enable AWS Signature Version 4, required for [minio](https://minio.io) servers                           |
| SCHEDULE                     |                                        |          | Backup schedule time, see explainatons below                                                                             |
| ENCRYPTION_PASSWORD          |                                        |          | Password to encrypt the backup. Can be decrypted using `openssl aes-256-cbc -d -in backup.sql.gz.enc -out backup.sql.gz` |
| DELETE_OLDER_THAN            |                                        |          | Delete old backups, see explanation and warning below                                                                    |

### Default Dump Options

Both single-database and all-database backups default to
`POSTGRES_EXTRA_OPTS="--no-owner --no-acl --no-tablespaces"`:

- `--no-owner`: omit source object ownership; restored objects belong to the restoring user.
- `--no-acl`: omit object access grants and revocations; configure target access separately.
- `--no-tablespaces`: omit source tablespace definitions and assignments; use target defaults.

Setting `POSTGRES_EXTRA_OPTS` replaces this entire list. To add an option, include
the defaults too, for example
`POSTGRES_EXTRA_OPTS="--no-owner --no-acl --no-tablespaces --verbose"`.
To preserve ownership, grants and tablespaces for disaster recovery, explicitly
set `POSTGRES_EXTRA_OPTS=""`.

### Backing Up All Databases and Role Passwords

Set `POSTGRES_DATABASE=all` to back up all databases with `pg_dumpall`. By default,
the script adds [`--no-role-passwords`](https://www.postgresql.org/docs/18/app-pg-dumpall.html)
so restoring the backup does not overwrite passwords of existing target roles,
including the PostgreSQL superuser (often `postgres`, or a custom name such as `root`).
Single-database backups use `pg_dump` and do not include global role definitions.

- Newly created roles have no password; set passwords separately before using password authentication.
- Role definitions and attributes (including superuser/login privileges) are still included. These options do not isolate the target's role configuration.
- To include source role password hashes, set `POSTGRES_DUMP_ROLE_PASSWORDS=true`. For full disaster recovery including ownership, grants and tablespaces too, also set `POSTGRES_EXTRA_OPTS=""`. Restoring source passwords can replace target passwords and cause later `psql` reconnections to fail if they still use the target's previous password.
- This change only affects newly generated backups. Existing backups still contain their original password statements; regenerate them with this option before restoring when possible.

Restore an `all` backup by connecting to an existing maintenance database, for example
`psql -h target -U postgres -d postgres -f dump.sql` (use `POSTGRES_DATABASE=postgres`
with the restore containers, not `all`). The SQL script creates and connects to the
original database names. On an initialized target, `CREATE ROLE` for the existing
bootstrap superuser can report an already-exists error; other restore errors still
need to be investigated. Do not use `--clean` when preserving existing roles and
their passwords, since dropping and recreating a role also removes its password.

### Automatic Periodic Backups

You can additionally set the `SCHEDULE` environment variable like `-e SCHEDULE="@daily"` to run the backup automatically.

More information about the scheduling can be found [here](https://pkg.go.dev/github.com/robfig/cron?utm_source=godoc#hdr-Predefined_schedules).

### Delete Old Backups

You can additionally set the `DELETE_OLDER_THAN` environment variable like `-e DELETE_OLDER_THAN="30 days ago"` to delete old backups.

WARNING: this will delete all files in the S3_PREFIX path, not just those created by this script.

### Encryption

You can additionally set the `ENCRYPTION_PASSWORD` environment variable like `-e ENCRYPTION_PASSWORD="superstrongpassword"` to encrypt the backup. It can be decrypted using `openssl aes-256-cbc -d -in backup.sql.gz.enc -out backup.sql.gz`.
