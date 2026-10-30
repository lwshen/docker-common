#!/usr/bin/env python3
"""SQL/archive backups and checked restores shared by the PostgreSQL images."""

import contextlib
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
import tarfile
import tempfile
import zipfile


HEADER = b"-- postgres-backup-metadata-v1: "
IDENTIFIER = r'(?:"(?:[^"]|"")*"|[A-Za-z_\x80-\uffff][\w$\x80-\uffff]*)'
EXTENSION = re.compile(r"^CREATE EXTENSION(?: IF NOT EXISTS)?\s+(" + IDENTIFIER + r")(?=\s|;)", re.I)
ROLE = re.compile(r"^(CREATE|ALTER) ROLE\s+(" + IDENTIFIER + r")(?=\s|;)", re.I)
ROLE_SETTING = re.compile(r"ALTER ROLE\s+" + IDENTIFIER + r"\s+IN DATABASE\s", re.I)
DATABASE_PROPERTY = re.compile(r"(?:ALTER DATABASE|COMMENT ON DATABASE|SECURITY LABEL .* ON DATABASE)\s|"
                               r"(?:GRANT|REVOKE)\b.*\bON DATABASE\s", re.I | re.S)
DATABASE_FILE = r"databases/[^/.][^/]*\.sql"


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
        port = os.environ.get("POSTGRES_PORT", "5432")
        if port.startswith("tcp://"):
            port = setting("POSTGRES_PORT_5432_TCP_PORT", "5432")
        self.args = ["-h", host, "-p", port,
                     "-U", setting("POSTGRES_USER")]
        os.environ["PGPASSWORD"] = setting("POSTGRES_PASSWORD")
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
    has_content = False
    with open(path, encoding="utf-8", errors="surrogateescape", newline="") as source:
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
                        if not block and not has_content:
                            yield "comment", "".join(buffer)
                            buffer = []
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
                    if not has_content:
                        yield "comment", "".join(buffer) + line[i:]
                        buffer = []
                        break
                    buffer.append(line[i:])
                    break
                elif line.startswith("/*", i):
                    buffer.append("/*")
                    block = 1
                    i += 2
                elif char in ("'", '"'):
                    has_content = True
                    escape_string = char == "'" and bool(buffer and buffer[-1] in ("E", "e") and
                        (len(buffer) < 2 or not re.match(r"[\w$]", buffer[-2][-1:])))
                    quote = char
                    buffer.append(char)
                    i += 1
                elif char == "$" and (i == 0 or not re.match(r"[\w$]", line[i - 1])) and (tag := re.match(r"\$(?:[A-Za-z_]\w*)?\$", line[i:])):
                    has_content = True
                    quote = tag.group()
                    buffer.append(quote)
                    i += len(quote)
                elif char == ";":
                    buffer.append(char)
                    statement = "".join(buffer)
                    yield "sql", statement
                    buffer = []
                    has_content = False
                    copy = bool(re.match(r"\s*COPY\b.*\bFROM stdin;\s*$", statement, re.S | re.I))
                    i += 1
                else:
                    has_content = has_content or not char.isspace()
                    buffer.append(char)
                    i += 1
            if buffer and not has_content and not block:
                yield "comment", "".join(buffer)
                buffer = []
        if buffer:
            yield "sql", "".join(buffer)


def connection_database(line):
    # psql meta-command quoting is not shell quoting. pg_dump emits either
    # a double-quoted SQL identifier or a double-quoted libpq connection string.
    value = re.sub(r"^\\(?:connect|c)\s+(?:-reuse-previous=\w+\s+)?", "", line.strip())
    if value.startswith('"'):
        if not value.endswith('"'):
            raise ValueError("Unterminated dump connection command.")
        value = value[1:-1].replace('""', '"')
    elif any(char.isspace() for char in value):
        raise ValueError("Unsupported dump connection command.")
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
    info = pg.query(database, """
        SELECT json_build_object(
          'server_version_num', current_setting('server_version_num')::int,
          'shared_preload_libraries', (SELECT setting FROM pg_settings WHERE name = 'shared_preload_libraries'),
          'extensions', COALESCE((SELECT json_agg(json_build_object(
            'name', e.extname, 'version', e.extversion, 'schema', n.nspname)
            ORDER BY e.extname) FROM pg_extension e
            JOIN pg_namespace n ON n.oid = e.extnamespace), '[]'::json))
    """)
    if info["shared_preload_libraries"] is None:
        print(f"{database}: shared_preload_libraries is unavailable to this role; preload validation is limited.", file=sys.stderr)
    return info


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

    def owns_backup(self, key, database):
        if not self.prefix:
            return False
        pattern = (re.escape(self.prefix) + r"/[0-9]{8}/" + re.escape(database) +
                   r"_[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{6}(?:_[0-9]{6})?\.(?:sql\.gz|tar(?:\.gz)?)(?:\.enc)?")
        return re.fullmatch(pattern, key) is not None

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
    older_than = os.environ.get("DELETE_OLDER_THAN", "None")
    if older_than not in ("None", "**None**", "") and not s3.prefix:
        raise ValueError("DELETE_OLDER_THAN requires a non-empty S3_PREFIX.")
    all_databases = pg.database == "all"
    options = os.environ.get("POSTGRES_EXTRA_OPTS", "auto")
    extra = shlex.split("--no-owner --no-acl --no-tablespaces" if options == "auto" else options)
    # These would redirect output or select an unsupported format behind our checks.
    for option in extra:
        if option in ("--help", "-?", "--version", "-V"):
            raise ValueError("POSTGRES_EXTRA_OPTS cannot replace the backup with help or version output.")
        if option in ("-f", "-F", "-Z") or option.startswith(("--file", "--format", "--compress", "-f", "-F", "-Z")):
            raise ValueError("POSTGRES_EXTRA_OPTS cannot change the managed SQL output file, format or compression.")
    if all_databases:
        enabled("POSTGRES_DUMP_ROLE_PASSWORDS")
    args = ["pg_dump", *pg.args, *extra, "--dbname", conninfo(pg.database)]
    with tempfile.TemporaryDirectory(prefix="postgres-backup-") as directory:
        work = Path(directory)
        if all_databases:
            compressed = backup_bundle(pg, work, extra)
        else:
            compressed = backup_sql(pg, work, args)
        now = dt.datetime.now(dt.timezone.utc)
        filename = f"{pg.database}_{now:%Y-%m-%d_%H%M%S_%f}" + (".tar.gz" if all_databases else ".sql.gz")
        password = os.environ.get("ENCRYPTION_PASSWORD", "None")
        if password not in ("None", "**None**", ""):
            encrypted = work / (compressed.name + ".enc")
            command(["openssl", "enc", "-aes-256-cbc", "-in", str(compressed), "-out", str(encrypted),
                     "-pass", "env:ENCRYPTION_PASSWORD"])
            compressed = encrypted
            filename += ".enc"
        key = "/".join(filter(None, [s3.prefix, now.strftime("%Y%m%d"), filename]))
        command([*s3.args, "s3", "cp", str(compressed), s3.uri(key), "--checksum-algorithm", "CRC32"])
        print(f"Backup uploaded: {s3.uri(key)}", flush=True)
        older_than = os.environ.get("DELETE_OLDER_THAN", "None")
        if older_than not in ("None", "**None**", ""):
            result = command(["date", "-d", older_than, "+%s"], stdout=subprocess.PIPE, text=True)
            cutoff = int(result.stdout)
            for obj in s3.objects():
                if not s3.owns_backup(obj["Key"], pg.database):
                    continue
                created = dt.datetime.fromisoformat(obj["LastModified"].replace("Z", "+00:00"))
                if created.timestamp() < cutoff:
                    command([*s3.args, "s3", "rm", s3.uri(obj["Key"])])
    print("Backup finished", flush=True)


def backup_sql(pg, work, args):
    raw = work / "dump.sql"
    print(f"Creating SQL backup of {pg.database}...", flush=True)
    with raw.open("wb") as output:
        command(args, stdout=output)
    if raw.stat().st_size == 0:
        raise ValueError("The dump was empty; no backup was uploaded.")
    databases = {pg.database: describe_database(pg, pg.database)}
    metadata = {"format_version": 1, "database": pg.database, "databases": databases,
                "dump_client": command([args[0], "--version"], stdout=subprocess.PIPE,
                                       text=True).stdout.strip(),
                "source_image": os.environ.get("POSTGRES_SOURCE_IMAGE"),
                "sql_sha256": file_hash(raw)}
    compressed = work / "dump.sql.gz"
    with gzip.open(compressed, "wb", compresslevel=6) as output, raw.open("rb") as source:
        output.write(HEADER + json.dumps(metadata, ensure_ascii=True).encode() + b"\n")
        shutil.copyfileobj(source, output)
    return compressed


def conninfo(database):
    return "dbname='" + database.replace("\\", "\\\\").replace("'", "\\'") + "'"


def database_pattern(pattern, name):
    """Match pg_dumpall database patterns: quoted literals, *, ? and regex."""
    parts = []
    quoted = False
    i = 0
    while i < len(pattern):
        char = pattern[i]
        if char == '"':
            if quoted and i + 1 < len(pattern) and pattern[i + 1] == '"':
                parts.append(re.escape('"'))
                i += 2
                continue
            quoted = not quoted
        elif quoted:
            parts.append(re.escape(char))
        elif char == '*':
            parts.append('.*')
        elif char == '?':
            parts.append('.')
        else:
            parts.append(char.lower())
        i += 1
    if quoted:
        raise ValueError("Unterminated quoted database pattern.")
    try:
        return re.fullmatch(''.join(parts), name) is not None
    except re.error as error:
        raise ValueError("Invalid database exclusion pattern.") from error


def bundle_name(database, used):
    """Readable, filesystem-safe archive path; the manifest keeps the exact name."""
    stem = "".join(char if char.isalnum() or char in "_-" or (char == "." and index)
                   else "".join(f"%{byte:02X}" for byte in char.encode())
                   for index, char in enumerate(database))
    name = stem
    suffix = 1
    # Case-insensitive filesystems would merge App.sql and app.sql on extraction.
    while name.casefold() in used:
        suffix += 1
        name = f"{stem}~{suffix}"
    used.add(name.casefold())
    return f"databases/{name}.sql"


def backup_bundle(pg, work, extra):
    dump_role_passwords = enabled("POSTGRES_DUMP_ROLE_PASSWORDS") and "--no-role-passwords" not in extra
    dump_extra = []
    excludes = []
    iterator = iter(extra)
    for option in iterator:
        if option == "--exclude-database":
            value = next(iterator, None)
            if value is None:
                raise ValueError("--exclude-database requires a pattern.")
            excludes.append(value)
        elif option.startswith("--exclude-database="):
            excludes.append(option.split("=", 1)[1])
        elif option != "--no-role-passwords":
            dump_extra.append(option)
    extra = dump_extra
    maintenance = os.environ.get("POSTGRES_MAINTENANCE_DATABASE", "postgres")
    names = pg.query(maintenance, "SELECT COALESCE(json_agg(datname ORDER BY datname), '[]'::json) "
                     "FROM pg_database WHERE datallowconn AND datconnlimit != -2")
    if excludes:
        # pg_dumpall --filter patterns use psql's SQL-name pattern syntax.
        names = [name for name in names if not any(database_pattern(pattern, name) for pattern in excludes)]
    if not names:
        raise ValueError("No connectable databases found; no backup was uploaded.")
    manifest = {"format_version": 3, "database": "all", "databases": {},
                "source_image": os.environ.get("POSTGRES_SOURCE_IMAGE"),
                "dump_client": command(["pg_dump", "--version"], stdout=subprocess.PIPE, text=True).stdout.strip()}
    bundle = work / "backup.tar.gz"
    used = set()
    # Each SQL file is added as soon as it is dumped, so only one database is
    # kept uncompressed on the temporary disk.
    with tarfile.open(bundle, "w:gz", compresslevel=6) as archive:
        for name in names:
            path = work / "database.sql"
            print(f"Dumping database {name!r}...", flush=True)
            info = describe_database(pg, name)
            command(["pg_dump", *pg.args, *extra, "--create",
                     "--file", str(path), "--dbname", conninfo(name)])
            arcname = bundle_name(name, used)
            info.update({"file": arcname, "sha256": file_hash(path)})
            manifest["databases"][name] = info
            archive.add(path, arcname=arcname, recursive=False)
            path.unlink()
        roles = work / "roles.sql"
        args = ["pg_dumpall", *pg.args, "--dbname", conninfo(maintenance), "--roles-only"]
        if not dump_role_passwords:
            args.append("--no-role-passwords")
        with roles.open("wb") as output:
            command(args, stdout=output)
        manifest["roles"] = {"file": roles.name, "sha256": file_hash(roles),
                             "includes_passwords": dump_role_passwords}
        tablespaces = work / "tablespaces.sql"
        with tablespaces.open("wb") as output:
            command(["pg_dumpall", *pg.args, "--dbname", conninfo(maintenance), "--tablespaces-only"], stdout=output)
        manifest["tablespaces"] = {"file": tablespaces.name, "sha256": file_hash(tablespaces)}
        metadata = work / "manifest.json"
        metadata.write_text(json.dumps(manifest, ensure_ascii=True, indent=2) + "\n")
        complete = work / "COMPLETE"
        complete.write_text(file_hash(metadata) + "\n")
        for path in [roles, tablespaces, metadata, complete]:
            archive.add(path, arcname=path.name, recursive=False)
    return bundle


def unpack(source, work):
    source = Path(source)
    if source.name.endswith(".enc"):
        setting("ENCRYPTION_PASSWORD")
        decrypted = work / "decrypted.sql.gz"
        command(["openssl", "enc", "-d", "-aes-256-cbc", "-in", str(source), "-out", str(decrypted),
                 "-pass", "env:ENCRYPTION_PASSWORD"])
        source = decrypted
    raw = work / "restore.sql"
    with contextlib.ExitStack() as stack:
        if source.name.endswith(".gz"):
            src = stack.enter_context(gzip.open(source, "rb"))
        elif source.name.endswith(".zip"):
            archive = stack.enter_context(zipfile.ZipFile(source))
            files = [name for name in archive.namelist() if not name.endswith("/")]
            if len(files) != 1:
                raise ValueError("ZIP backups must contain exactly one SQL file.")
            src = stack.enter_context(archive.open(files[0]))
        else:
            src = stack.enter_context(source.open("rb"))
        dst = stack.enter_context(raw.open("wb"))
        first = src.readline()
        metadata = None
        if first.startswith(HEADER):
            metadata = json.loads(first[len(HEADER):])
            if metadata.get("format_version") != 1:
                raise ValueError("Unsupported backup metadata version.")
        else:
            dst.write(first)
        shutil.copyfileobj(src, dst)
    if not raw.stat().st_size:
        raise ValueError("The backup SQL is empty.")
    if metadata and file_hash(raw) != metadata.get("sql_sha256"):
        raise ValueError("Backup SQL checksum mismatch; restore was not started.")
    return raw, metadata


def preflight(pg, raw, metadata, databases=None):
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
    if databases is None:
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
            if target["server_version_num"] // 10000 < source["server_version_num"] // 10000:
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
                if not enabled("RESTORE_ALLOW_EXTENSION_VERSION_MISMATCH"):
                    raise ValueError(f"{database}: extension {extension!r} version mismatch: source {expected[extension]}, target {version}. Use matching packages or explicitly set RESTORE_ALLOW_EXTENSION_VERSION_MISMATCH=true after reviewing compatibility.")
                print(f"{database}: allowing extension {extension!r} version mismatch: source {expected[extension]}, target {version}.", file=sys.stderr)
            for dependency in ([] if extension in installed else available[extension]["requires"] or []):
                if dependency not in ready:
                    raise ValueError(f"{database}: extension {extension!r} requires {dependency!r} before it is created. Match the source versions or prepare the dependency in this database first.")
            ready.add(extension)
        if source and source.get("shared_preload_libraries") is not None and target.get("shared_preload_libraries") is not None:
            def libraries(value):
                return {part.strip().strip('"').split("/")[-1] for part in (value or "").split(",") if part.strip()}
            required = libraries(source["shared_preload_libraries"]) & set(extensions)
            missing = required - libraries(target["shared_preload_libraries"])
            if missing:
                raise ValueError(f"{database}: shared_preload_libraries is missing {', '.join(sorted(missing))}; configure and restart the target.")
    roles = pg.query(pg.database, "SELECT COALESCE(json_agg(rolname), '[]'::json) FROM pg_roles")
    print("Restore preflight passed", flush=True)
    return set(roles), any(name is not None for name in databases)


def restore(source, work):
    source = Path(source)
    if source.name.endswith((".tar", ".tar.enc")):
        raise ValueError("The previous .tar bundle format is no longer supported; restore a .tar.gz bundle.")
    if source.name.endswith((".tar.gz", ".tar.gz.enc")):
        if source.name.endswith(".enc"):
            setting("ENCRYPTION_PASSWORD")
            decrypted = work / "backup.tar.gz"
            command(["openssl", "enc", "-d", "-aes-256-cbc", "-in", str(source), "-out", str(decrypted),
                     "-pass", "env:ENCRYPTION_PASSWORD"])
            source = decrypted
        restore_bundle(source, work)
        return
    if os.environ.get("RESTORE_DATABASE"):
        raise ValueError("Database selection requires an archive bundle; legacy SQL cannot be filtered safely.")
    pg = Postgres()
    raw, metadata = unpack(source, work)
    roles = set(pg.query(pg.database, "SELECT COALESCE(json_agg(rolname), '[]'::json) FROM pg_roles"))
    declarations = {None: []}
    prepared = work / "prepared.sql"
    raw.rename(prepared)
    prepare_roles(prepared, prepared, roles, declarations)
    _, multiple = preflight(pg, prepared, metadata, declarations)
    if os.environ.get("DROP_PUBLIC", "no") == "yes":
        if multiple:
            raise ValueError("DROP_PUBLIC=yes is not supported for all-database backups.")
        command([*pg.psql(pg.database), "-c", "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"])
    command([*pg.psql(pg.database), "-f", str(prepared)])
    print("Restore complete", flush=True)


def prepare_roles(raw, prepared, roles, declarations=None):
    role_policy = os.environ.get("RESTORE_EXISTING_ROLES", "preserve")
    if role_policy not in ("preserve", "apply"):
        raise ValueError("RESTORE_EXISTING_ROLES must be preserve or apply.")
    current = None
    # In-place compaction never writes ahead of the scanner: each replacement
    # is shorter than its original statement. Keep only one full SQL file.
    inplace = raw == prepared
    with prepared.open("r+b" if inplace else "wb") as output:
        for kind, chunk in sql_chunks(raw):
            if declarations is not None:
                if kind == "meta" and re.match(r"\\(?:connect|c)\s", chunk):
                    current = connection_database(chunk)
                    declarations.setdefault(current, [])
                elif kind == "sql" and (extension := EXTENSION.match(chunk.strip())):
                    declarations[current].append(identifier(extension.group(1)))
            match = ROLE.match(chunk.strip()) if kind == "sql" else None
            if match and identifier(match.group(2)) in roles and (match.group(1).upper() == "CREATE" or role_policy == "preserve"):
                # Preserve existing target passwords AND role attributes. Only
                # top-level CREATE/ALTER ROLE from the dump are skipped.
                output.write(b"\n")
            else:
                output.write(chunk.encode("utf-8", errors="surrogateescape"))
        output.truncate()
    return prepared


def read_bundle(source, work):
    """Extract only regular files at known paths; never follow archive links or paths."""
    destination = work / "bundle"
    (destination / "databases").mkdir(parents=True)
    with tarfile.open(source, "r:gz") as archive:
        seen = set()
        for member in archive:
            if (not member.isfile() or member.name in seen or
                    not re.fullmatch(r"manifest\.json|COMPLETE|roles\.sql|tablespaces\.sql|" + DATABASE_FILE, member.name)):
                raise ValueError("Invalid or duplicate backup bundle member.")
            seen.add(member.name)
            with archive.extractfile(member) as src, (destination / member.name).open("wb") as dst:
                shutil.copyfileobj(src, dst)
    metadata = destination / "manifest.json"
    complete = destination / "COMPLETE"
    if not metadata.is_file() or not complete.is_file() or complete.read_text().strip() != file_hash(metadata):
        raise ValueError("Incomplete backup bundle or manifest checksum mismatch.")
    manifest = json.loads(metadata.read_text())
    if manifest.get("format_version") != 3 or manifest.get("database") != "all" or not manifest.get("databases"):
        raise ValueError("Unsupported or empty backup bundle manifest.")
    records = [*manifest["databases"].values(), manifest["roles"], manifest["tablespaces"]]
    expected = {"manifest.json", "COMPLETE"}
    for index, record in enumerate(records):
        name = record["file"]
        pattern = (DATABASE_FILE if index < len(manifest["databases"])
                   else r"roles\.sql" if index == len(manifest["databases"]) else r"tablespaces\.sql")
        if not re.fullmatch(pattern, name) or name in expected:
            raise ValueError("Invalid backup manifest file reference.")
        expected.add(name)
        path = destination / name
        if not path.is_file() or file_hash(path) != record["sha256"]:
            raise ValueError(f"Backup file checksum mismatch: {name}; restore was not started.")
    if seen != expected:
        raise ValueError("Backup bundle does not match its manifest.")
    return destination, manifest


def prepare_database(path, database, exists, restore_roles):
    """Rewrite a pg_dump --create script in place to run inside the target database.

    CREATE DATABASE is returned so it only runs when the database is missing.
    Database-level settings only apply to databases created by this restore;
    role-specific settings additionally require restored roles.
    """
    extensions = []
    creation = None
    # In-place compaction never writes ahead of the scanner (see prepare_roles).
    with path.open("r+b") as output:
        for kind, chunk in sql_chunks(path):
            statement = chunk.strip()
            keep = True
            if kind == "meta" and re.match(r"\\(?:connect|c)\s", chunk):
                if connection_database(chunk) != database:
                    raise ValueError(f"Unexpected connection command in the backup of {database!r}.")
                keep = False
            elif kind == "sql":
                if match := EXTENSION.match(statement):
                    extensions.append(identifier(match.group(1)))
                if re.match(r"CREATE DATABASE\s", statement, re.I):
                    creation = statement
                    keep = False
                elif ROLE_SETTING.match(statement):
                    keep = restore_roles and not exists
                elif DATABASE_PROPERTY.match(statement):
                    keep = not exists
            output.write(chunk.encode("utf-8", errors="surrogateescape") if keep else b"\n")
        output.truncate()
    if creation is None:
        raise ValueError(f"Missing CREATE DATABASE statement for {database!r}.")
    return extensions, creation


def restore_bundle(source, work):
    folder, manifest = read_bundle(source, work)
    pg = Postgres()
    restore_roles = enabled("RESTORE_ROLES")
    restore_tablespaces = enabled("RESTORE_TABLESPACES")
    selected = os.environ.get("RESTORE_DATABASE", "")
    if selected and selected not in manifest["databases"]:
        raise ValueError(f"Database {selected!r} is not in this backup.")
    databases = {name: info for name, info in manifest["databases"].items() if not selected or name == selected}
    if os.environ.get("DROP_PUBLIC", "no") == "yes":
        raise ValueError("DROP_PUBLIC=yes is not supported for archive bundles; restore into empty databases.")
    existing = pg.query(pg.database, "SELECT COALESCE(json_agg(datname), '[]'::json) FROM pg_database")
    # Parse and validate ALL selected databases before any target mutation.
    declarations = {}
    creations = {}
    for name, info in databases.items():
        declarations[name], creations[name] = prepare_database(
            folder / info["file"], name, name in existing, restore_roles)
    roles, _ = preflight(pg, None, manifest, declarations)
    prepared = prepare_roles(folder / manifest["roles"]["file"], work / "roles-prepared.sql", roles)
    if restore_roles:
        command([*pg.psql(pg.database), "-f", str(prepared)])
    if restore_tablespaces:
        command([*pg.psql(pg.database), "-f", str(folder / manifest["tablespaces"]["file"])])
    for name, info in databases.items():
        print(f"Restoring database {name!r}...", flush=True)
        if name not in existing:
            command([*pg.psql(pg.database), "-c", creations[name]])
        command([*pg.psql(name), "-f", str(folder / info["file"])])
    print("Restore complete", flush=True)


def restore_s3():
    s3 = S3()
    objects = [obj for obj in s3.objects() if obj["Key"].endswith((".sql.gz", ".sql.gz.enc", ".tar.gz", ".tar.gz.enc"))]
    if not objects:
        raise ValueError("No supported backups found in the configured S3 prefix.")
    latest = max(objects, key=lambda obj: (obj["LastModified"], obj["Key"]))
    print(f"Restoring {s3.uri(latest['Key'])}", flush=True)
    with tempfile.TemporaryDirectory(prefix="postgres-restore-") as directory:
        work = Path(directory)
        downloaded = work / Path(latest["Key"]).name
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
    except (ValueError, KeyError, TypeError, OSError, subprocess.CalledProcessError, zipfile.BadZipFile, tarfile.TarError, EOFError) as error:
        # CalledProcessError may include SQL or connection arguments; the child
        # already printed its diagnostic, so do not echo its entire command.
        message = f"Command failed with exit status {error.returncode}." if isinstance(error, subprocess.CalledProcessError) else str(error)
        print(f"ERROR: {message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
