# PostgreSQL backup validation

`backup_tools.py` is shared by all three PostgreSQL images. The existing shell
entry points and SQL/gzip backup layout are retained. Build images with the
repository root as the Docker context; `.dockerignore` limits that context to
the required PostgreSQL source files.

All-database backups are `.tar.gz` bundles of plain `pg_dump --create` SQL files
(`databases/<database>.sql`) described by `manifest.json` (format version 3).
Before loading a file into its database, restore removes `CREATE DATABASE` and
`\connect`, and keeps database-level settings only for databases it creates.

The first SQL comment in a new single-database backup is
`-- postgres-backup-metadata-v1: <JSON>`. It records a payload checksum, per-database
server and extension information, the dump client version and an optional source
image supplied by the deployment. Removing or modifying this header disables or
invalidates verification; do not edit generated backup payloads. Metadata does not
make snapshots across different databases simultaneous.

Restore preflight is read-only. It checks extension prerequisites in SQL execution
order, before processing roles, creating databases, dropping schemas or loading
rows. Existing role CREATE/ALTER statements are handled separately so expected
bootstrap-role conflicts do not hide unrelated SQL errors. The SQL scanner only
handles complete top-level statements: dollar-quoted function bodies and COPY
data are preserved.

Validation does not execute extension installation scripts in advance, so library
loading errors and other environment differences may still cause restore to fail.
The default is to stop at the first such error. Whole-cluster restores cannot be
wrapped in one transaction; retry from a clean target after a partial restore.

Run the standard-library unit tests:

```sh
python3 -m unittest discover -s postgres-common/tests -v
```

Run integration tests with Docker and PostgreSQL 18 client tools. These create two
temporary PostgreSQL 18 containers and fixture extensions, test version/dependency
failures before database creation, successful restore, preservation of target
role attributes/passwords, manual `psql` restore of a bundle SQL file, legacy
gzip/ZIP compatibility, and SQL error handling:

```sh
python3 postgres-common/tests/integration.py
```

Regression coverage also includes restricted backup roles, native SQL_ASCII and
legacy LATIN1 bytes, template and invalid databases, database-name quoting,
legacy export options, database tablespaces and database-specific role settings.
