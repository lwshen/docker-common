#!/usr/bin/env python3
"""Checked SQL backups and read-only restore preflight for the PostgreSQL images."""

import datetime as dt
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import zipfile


HEADER = b"-- postgres-backup-metadata-v1: "
IDENTIFIER = r'(?:"(?:[^"]|"")*"|[A-Za-z_\x80-\uffff][\w$\x80-\uffff]*)'
EXTENSION = re.compile(r"^CREATE EXTENSION(?: IF NOT EXISTS)?\s+(" + IDENTIFIER + r")(?=\s|;)", re.I)
ROLE = re.compile(r"^(CREATE|ALTER) ROLE\s+(" + IDENTIFIER + r")(?=\s|;)", re.I)


def identifier(value):
    return value[1:-1].replace('""', '"') if value.startswith('"') else value.lower()


def setting(name, default=None):
    value = os.environ.get(name, default)
    if value in (None, "", "None", "**None**"):
        raise ValueError(f"You need to set {name}.")
    return value


def enabled(name, default="false"):
    value = os.environ.get(name, default)
    if value not in ("true", "false"):
        raise ValueError(f"{name} must be true or false.")
    return value == "true"


def command(args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


class Postgres:
    def __init__(self):
        host = os.environ.get("POSTGRES_HOST", "None")
        if host in ("None", "**None**", ""):
            host = setting("POSTGRES_PORT_5432_TCP_ADDR")
        self.args = ["-h", host, "-p", os.environ.get("POSTGRES_PORT", "5432"),
                     "-U", setting("POSTGRES_USER")]
        os.environ["PGPASSWORD"] = setting("POSTGRES_PASSWORD")
        os.environ["PGCLIENTENCODING"] = "UTF8"
        self.database = setting("POSTGRES_DATABASE")

    def psql(self, database):
        # Always use conninfo quoting, including for database names containing '='.
        dbname = database.replace("\\", "\\\\").replace("'", "\\'")
        return ["psql", "-X", "-w", "-v", "ON_ERROR_STOP=1", *self.args,
                "-d", "dbname='" + dbname + "'"]

    def query(self, database, sql):
        result = command([*self.psql(database), "-qAt", "-c", sql],
                         stdout=subprocess.PIPE, text=True)
        return json.loads(result.stdout)


def sql_chunks(path):
    """Read pg_dump SQL without treating function bodies or COPY rows as commands.

    Each SQL statement, top-level comment/meta-command and COPY data line is
    yielded separately. Rewriting only complete top-level role statements keeps
    user functions and table data intact.
    """
    buffer = []
    quote = None
    escape_string = False
    block = 0
    copy = False
    with open(path, encoding="utf-8", newline="") as source:
        for line in source:
            if copy:
                yield "data", line
                if line.rstrip("\r\n") == r"\.":
                    copy = False
                continue
            if not buffer and (not line.strip() or line.startswith("--")):
                yield "comment", line
                continue
            if not buffer and line.startswith("\\"):
                yield "meta", line
                continue
            i = 0
            while i < len(line):
                char = line[i]
                if block:
                    if line.startswith("/*", i):
                        buffer.append("/*")
                        block += 1
                        i += 2
                    elif line.startswith("*/", i):
                        buffer.append("*/")
                        block -= 1
                        i += 2
                    else:
                        buffer.append(char)
                        i += 1
                elif quote:
                    if line.startswith(quote, i):
                        buffer.append(quote)
                        i += len(quote)
                        if quote in ("'", '"') and line.startswith(quote, i):
                            buffer.append(quote)
                            i += len(quote)
                        else:
                            quote = None
                    elif quote == "'" and escape_string and char == "\\":
                        buffer.append(line[i:i + 2])
                        i += 2
                    else:
                        buffer.append(char)
                        i += 1
                elif line.startswith("--", i):
                    buffer.append(line[i:])
                    break
                elif line.startswith("/*", i):
                    buffer.append("/*")
                    block = 1
                    i += 2
                elif char in ("'", '"'):
                    escape_string = char == "'" and bool(re.search(r"(?i)(?<![\w$])E$", "".join(buffer)))
                    quote = char
                    buffer.append(char)
                    i += 1
                elif char == "$" and (tag := re.match(r"\$(?:[A-Za-z_]\w*)?\$", line[i:])):
                    quote = tag.group()
                    buffer.append(quote)
                    i += len(quote)
                elif char == ";":
                    buffer.append(char)
                    statement = "".join(buffer)
                    yield "sql", statement
                    buffer = []
                    copy = bool(re.match(r"\s*COPY\b.*\bFROM stdin;\s*$", statement, re.S | re.I))
                    i += 1
                else:
                    buffer.append(char)
                    i += 1
            if buffer and not "".join(buffer).strip():
                yield "comment", "".join(buffer)
                buffer = []
        if buffer:
            yield "sql", "".join(buffer)


def connection_database(line):
    parts = shlex.split(line.strip()[1:])
    args = [part for part in parts[1:] if not part.startswith("-reuse-previous=")]
    if len(args) != 1:
        raise ValueError("Unsupported dump connection command; inspect the SQL before restoring.")
    value = args[0]
    if value.startswith("dbname="):
        match = re.fullmatch(r"dbname='((?:\\.|[^'])*)'", value)
        if not match:
            raise ValueError("Unsupported dump database connection string.")
        value = re.sub(r"\\(.)", r"\1", match.group(1))
    return value


def plan(path):
    databases = {None: []}
    current = None
    for kind, chunk in sql_chunks(path):
        if kind == "meta" and re.match(r"\\(?:connect|c)\s", chunk):
            current = connection_database(chunk)
            databases.setdefault(current, [])
        elif kind == "sql":
            if match := EXTENSION.match(chunk.strip()):
                databases[current].append(identifier(match.group(1)))
    return databases


def file_hash(path):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def describe_database(pg, database):
    return pg.query(database, """
        SELECT json_build_object(
          'server_version_num', current_setting('server_version_num')::int,
          'shared_preload_libraries', current_setting('shared_preload_libraries'),
          'extensions', COALESCE((SELECT json_agg(json_build_object(
            'name', e.extname, 'version', e.extversion, 'schema', n.nspname)
            ORDER BY e.extname) FROM pg_extension e
            JOIN pg_namespace n ON n.oid = e.extnamespace), '[]'::json))
    """)


class S3:
    def __init__(self):
        self.bucket = setting("S3_BUCKET")
        self.prefix = os.environ.get("S3_PREFIX", "backup").strip("/")
        os.environ["AWS_ACCESS_KEY_ID"] = setting("S3_ACCESS_KEY_ID")
        os.environ["AWS_SECRET_ACCESS_KEY"] = setting("S3_SECRET_ACCESS_KEY")
        os.environ["AWS_DEFAULT_REGION"] = os.environ.get("S3_REGION", "us-west-1")
        self.args = ["aws"]
        endpoint = os.environ.get("S3_ENDPOINT", "None")
        if endpoint not in ("None", "**None**", ""):
            self.args += ["--endpoint-url", endpoint]

    def objects(self):
        result = command([*self.args, "s3api", "list-objects-v2", "--bucket", self.bucket,
                          "--prefix", self.prefix + "/" if self.prefix else "", "--output", "json"],
                         stdout=subprocess.PIPE, text=True)
        return json.loads(result.stdout).get("Contents", [])

    def uri(self, key):
        return f"s3://{self.bucket}/{key}"


def backup():
    pg = Postgres()
    s3 = S3()
    all_databases = pg.database == "all"
    extra = shlex.split(os.environ.get("POSTGRES_EXTRA_OPTS", "--no-owner --no-acl --no-tablespaces"))
    # These would redirect output or select an unsupported format behind our checks.
    for option in extra:
        if option in ("--help", "-?", "--version", "-V"):
            raise ValueError("POSTGRES_EXTRA_OPTS cannot replace the backup with help or version output.")
        if option in ("-f", "-F", "-Z") or option.startswith(("--file", "--format", "--compress", "-f", "-F", "-Z")):
            raise ValueError("POSTGRES_EXTRA_OPTS cannot change the managed SQL output file, format or compression.")
    args = ["pg_dumpall" if all_databases else "pg_dump", *pg.args, *extra, "--encoding=UTF8"]
    if all_databases:
        if not enabled("POSTGRES_DUMP_ROLE_PASSWORDS"):
            args.append("--no-role-passwords")
    else:
        dbname = pg.database.replace("\\", "\\\\").replace("'", "\\'")
        args += ["--dbname", "dbname='" + dbname + "'"]
    with tempfile.TemporaryDirectory(prefix="postgres-backup-") as directory:
        work = Path(directory)
        raw = work / "dump.sql"
        print(f"Creating SQL backup of {pg.database}...", flush=True)
        with raw.open("wb") as output:
            command(args, stdout=output)
        if raw.stat().st_size == 0:
            raise ValueError("The dump was empty; no backup was uploaded.")
        databases = {}
        for name in plan(raw):
            database = name or ("postgres" if all_databases else pg.database)
            databases[database] = describe_database(pg, database)
        metadata = {"format_version": 1, "database": pg.database, "databases": databases,
                    "dump_client": command([args[0], "--version"], stdout=subprocess.PIPE,
                                           text=True).stdout.strip(),
                    "source_image": os.environ.get("POSTGRES_SOURCE_IMAGE"),
                    "sql_sha256": file_hash(raw)}
        compressed = work / "dump.sql.gz"
        with gzip.open(compressed, "wb", compresslevel=6) as output, raw.open("rb") as source:
            output.write(HEADER + json.dumps(metadata, ensure_ascii=True).encode() + b"\n")
            shutil.copyfileobj(source, output)
        now = dt.datetime.now(dt.timezone.utc)
        filename = f"{pg.database}_{now:%Y-%m-%d_%H%M%S_%f}.sql.gz"
        password = os.environ.get("ENCRYPTION_PASSWORD", "None")
        if password not in ("None", "**None**", ""):
            encrypted = work / "dump.sql.gz.enc"
            command(["openssl", "enc", "-aes-256-cbc", "-in", str(compressed), "-out", str(encrypted),
                     "-pass", "env:ENCRYPTION_PASSWORD"])
            compressed = encrypted
            filename += ".enc"
        key = "/".join(filter(None, [s3.prefix, now.strftime("%Y%m%d"), filename]))
        command([*s3.args, "s3", "cp", str(compressed), s3.uri(key), "--checksum-algorithm", "CRC32"])
        print(f"SQL backup uploaded: {s3.uri(key)}", flush=True)
        older_than = os.environ.get("DELETE_OLDER_THAN", "None")
        if older_than not in ("None", "**None**", ""):
            result = command(["date", "-d", older_than, "+%s"], stdout=subprocess.PIPE, text=True)
            cutoff = int(result.stdout)
            for obj in s3.objects():
                created = dt.datetime.fromisoformat(obj["LastModified"].replace("Z", "+00:00"))
                if created.timestamp() < cutoff:
                    command([*s3.args, "s3", "rm", s3.uri(obj["Key"])])
    print("SQL backup finished", flush=True)


def unpack(source, work):
    source = Path(source)
    if source.name.endswith(".enc"):
        setting("ENCRYPTION_PASSWORD")
        decrypted = work / "decrypted.sql.gz"
        command(["openssl", "enc", "-d", "-aes-256-cbc", "-in", str(source), "-out", str(decrypted),
                 "-pass", "env:ENCRYPTION_PASSWORD"])
        source = decrypted
    sql = work / "unpacked.sql"
    if source.name.endswith(".gz"):
        with gzip.open(source, "rb") as src, sql.open("wb") as dst:
            shutil.copyfileobj(src, dst)
    elif source.name.endswith(".zip"):
        with zipfile.ZipFile(source) as archive:
            files = [name for name in archive.namelist() if not name.endswith("/")]
            if len(files) != 1:
                raise ValueError("ZIP backups must contain exactly one SQL file.")
            with archive.open(files[0]) as src, sql.open("wb") as dst:
                shutil.copyfileobj(src, dst)
    else:
        shutil.copyfile(source, sql)
    raw = work / "restore.sql"
    with sql.open("rb") as src, raw.open("wb") as dst:
        first = src.readline()
        metadata = None
        if first.startswith(HEADER):
            metadata = json.loads(first[len(HEADER):])
            if metadata.get("format_version") != 1:
                raise ValueError("Unsupported backup metadata version.")
        else:
            dst.write(first)
        shutil.copyfileobj(src, dst)
    sql.unlink()
    if not raw.stat().st_size:
        raise ValueError("The backup SQL is empty.")
    if metadata and file_hash(raw) != metadata.get("sql_sha256"):
        raise ValueError("Backup SQL checksum mismatch; restore was not started.")
    return raw, metadata


def preflight(pg, raw, metadata):
    if pg.database == "all":
        raise ValueError("Connect to an existing maintenance database such as postgres, not 'all'.")
    target = describe_database(pg, pg.database)
    available = pg.query(pg.database, """
        SELECT COALESCE(json_agg(json_build_object('name', a.name, 'version', a.default_version,
          'requires', v.requires)), '[]'::json)
        FROM pg_available_extensions a JOIN pg_available_extension_versions v
        ON v.name = a.name AND v.version = a.default_version
    """)
    available = {extension["name"]: extension for extension in available}
    existing = pg.query(pg.database, "SELECT COALESCE(json_agg(datname), '[]'::json) FROM pg_database")
    databases = plan(raw)
    if not metadata:
        print("Legacy backup: source extension versions/checksum are unavailable; checking declared dependencies.",
              file=sys.stderr)
    for name, extensions in databases.items():
        database = name or pg.database
        info = describe_database(pg, database) if database in existing else None
        installed = {ext["name"]: ext["version"] for ext in (info or {}).get("extensions", [])}
        source = None
        if metadata:
            source_name = name or ("postgres" if metadata["database"] == "all" else metadata["database"])
            source = metadata["databases"][source_name]
            if target["server_version_num"] // 10000 != source["server_version_num"] // 10000:
                raise ValueError(f"{database}: PostgreSQL major version mismatch: source {source['server_version_num'] // 10000}, target {target['server_version_num'] // 10000}; prepare a matching target first.")
        expected = {ext["name"]: ext["version"] for ext in (source or {}).get("extensions", [])}
        ready = set(installed)
        # pg_dump creates databases from template0, which includes plpgsql on
        # standard PostgreSQL installations; it is not normally dumped itself.
        if info is None and "plpgsql" in available:
            ready.add("plpgsql")
        for extension in extensions:
            if extension not in available:
                raise ValueError(f"{database}: extension {extension!r} is unavailable on the target server. Install its package first.")
            version = installed.get(extension, available[extension]["version"])
            if extension in expected and version != expected[extension]:
                raise ValueError(f"{database}: extension {extension!r} version mismatch: source {expected[extension]}, target {version}. Use matching extension packages.")
            for dependency in ([] if extension in installed else available[extension]["requires"] or []):
                if dependency not in ready:
                    raise ValueError(f"{database}: extension {extension!r} requires {dependency!r} before it is created. Match the source versions or prepare the dependency in this database first.")
            ready.add(extension)
        if source:
            def libraries(value):
                return {part.strip().strip('"').split("/")[-1] for part in value.split(",") if part.strip()}
            required = libraries(source["shared_preload_libraries"]) & set(extensions)
            missing = required - libraries(target["shared_preload_libraries"])
            if missing:
                raise ValueError(f"{database}: shared_preload_libraries is missing {', '.join(sorted(missing))}; configure and restart the target.")
    roles = pg.query(pg.database, "SELECT COALESCE(json_agg(rolname), '[]'::json) FROM pg_roles")
    print("Restore preflight passed", flush=True)
    return set(roles), any(name is not None for name in databases)


def restore(source, work):
    pg = Postgres()
    raw, metadata = unpack(source, work)
    roles, multiple = preflight(pg, raw, metadata)
    role_policy = os.environ.get("RESTORE_EXISTING_ROLES", "preserve")
    if role_policy not in ("preserve", "apply"):
        raise ValueError("RESTORE_EXISTING_ROLES must be preserve or apply.")
    prepared = work / "prepared.sql"
    with prepared.open("w", encoding="utf-8", newline="") as output:
        for kind, chunk in sql_chunks(raw):
            match = ROLE.match(chunk.strip()) if kind == "sql" else None
            if match and identifier(match.group(2)) in roles and (match.group(1).upper() == "CREATE" or role_policy == "preserve"):
                # Preserve existing target passwords AND role attributes. Only
                # top-level CREATE/ALTER ROLE from the dump are skipped.
                output.write("-- Existing target role definition preserved.\n")
            else:
                output.write(chunk)
    if os.environ.get("DROP_PUBLIC", "no") == "yes":
        if multiple:
            raise ValueError("DROP_PUBLIC=yes is not supported for all-database backups.")
        command([*pg.psql(pg.database), "-c", "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"])
    command([*pg.psql(pg.database), "-f", str(prepared)])
    print("Restore complete", flush=True)


def restore_s3():
    s3 = S3()
    objects = [obj for obj in s3.objects() if obj["Key"].endswith((".sql.gz", ".sql.gz.enc"))]
    if not objects:
        raise ValueError("No SQL backups found in the configured S3 prefix.")
    latest = max(objects, key=lambda obj: (obj["LastModified"], obj["Key"]))
    print(f"Restoring {s3.uri(latest['Key'])}", flush=True)
    with tempfile.TemporaryDirectory(prefix="postgres-restore-") as directory:
        work = Path(directory)
        downloaded = work / ("backup.sql.gz.enc" if latest["Key"].endswith(".enc") else "backup.sql.gz")
        command([*s3.args, "s3", "cp", s3.uri(latest["Key"]), str(downloaded)])
        restore(downloaded, work)


def main():
    try:
        if sys.argv[1] == "backup":
            backup()
        elif sys.argv[1] == "restore-s3":
            restore_s3()
        elif sys.argv[1] == "restore-file":
            with tempfile.TemporaryDirectory(prefix="postgres-restore-") as directory:
                restore(setting("BACKUP_FILE", "/backup/dump.sql"), Path(directory))
        else:
            raise ValueError("Unknown operation.")
    except (ValueError, OSError, subprocess.CalledProcessError, zipfile.BadZipFile, EOFError) as error:
        # CalledProcessError may include SQL or connection arguments; the child
        # already printed its diagnostic, so do not echo its entire command.
        message = f"Command failed with exit status {error.returncode}." if isinstance(error, subprocess.CalledProcessError) else str(error)
        print(f"ERROR: {message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
