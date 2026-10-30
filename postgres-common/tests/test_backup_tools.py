import contextlib
import gzip
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import tarfile
import unittest
from unittest import mock
import zipfile


SPEC = importlib.util.spec_from_file_location("backup_tools", Path(__file__).parents[1] / "backup_tools.py")
tools = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tools)


class TempCase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.work = Path(self.directory.name)
        self.env = mock.patch.dict(os.environ, {
            "POSTGRES_HOST": "localhost", "POSTGRES_USER": "postgres", "POSTGRES_PASSWORD": "test",
            "POSTGRES_DATABASE": "test", "POSTGRES_EXTRA_OPTS": "", "ENCRYPTION_PASSWORD": "None",
            "DELETE_OLDER_THAN": "None", "DROP_PUBLIC": "no", "RESTORE_EXISTING_ROLES": "preserve",
        })
        self.env.start()
        self.addCleanup(self.env.stop)

    def write(self, text, name="dump.sql"):
        path = self.work / name
        path.write_text(text)
        return path


class BackupTests(TempCase):
    def test_scanner_preserves_function_and_copy_data(self):
        text = '''CREATE ROLE root;
CREATE FUNCTION example() RETURNS text AS $body$
CREATE ROLE root;
\\connect imaginary
CREATE EXTENSION missing;
$body$ LANGUAGE sql;
COPY example_data (value) FROM stdin;
CREATE ROLE root;
\\connect copy_data
\\.
CREATE EXTENSION IF NOT EXISTS "CaseSensitive" WITH SCHEMA public;
'''
        path = self.write(text)
        self.assertEqual(tools.plan(path), {None: ["CaseSensitive"]})
        self.assertEqual("".join(chunk for _, chunk in tools.sql_chunks(path)), text)

    def test_standard_and_escape_strings_do_not_hide_following_commands(self):
        path = self.write("SELECT 'a\\';\nSELECT E'a\\\'b';\nCREATE EXTENSION hstore;\n")
        self.assertEqual(tools.plan(path), {None: ["hstore"]})

    def test_connection_names(self):
        self.assertEqual(tools.connection_database(r'\connect test'), 'test')
        self.assertEqual(tools.connection_database(r'''\connect -reuse-previous=on "dbname='back\\slash""quote'"'''), 'back\\slash"quote')
        self.assertEqual(tools.connection_database(r'''\connect -reuse-previous=on "dbname='a b'"'''), 'a b')
        self.assertEqual(tools.connection_database(r'''\connect -reuse-previous=on "dbname='a\'b'"'''), "a'b")

    def test_preserve_existing_role_definitions_without_touching_function_data(self):
        raw = self.write("CREATE ROLE postgres;\nALTER ROLE postgres WITH SUPERUSER PASSWORD 'source';\n"
                         "CREATE ROLE business;\nCREATE FUNCTION f() RETURNS text AS $$ALTER ROLE postgres;$$ LANGUAGE sql;\n")
        with mock.patch.object(tools.Postgres, "query", return_value=["postgres"]), \
                mock.patch.object(tools, "preflight", return_value=({"postgres"}, False)), \
                mock.patch.object(tools, "command") as command:
            tools.restore(raw, self.work)
        prepared = (self.work / "prepared.sql").read_text()
        self.assertNotIn("PASSWORD 'source'", prepared)
        self.assertIn("CREATE ROLE business;", prepared)
        self.assertIn("$$ALTER ROLE postgres;$$", prepared)
        self.assertIn("ON_ERROR_STOP=1", command.call_args.args[0])

    def test_apply_role_policy_skips_duplicate_create_but_keeps_alter(self):
        os.environ["RESTORE_EXISTING_ROLES"] = "apply"
        raw = self.write("CREATE ROLE postgres;\nALTER ROLE postgres WITH CONNECTION LIMIT 3;\n")
        with mock.patch.object(tools.Postgres, "query", return_value=["postgres"]), \
                mock.patch.object(tools, "preflight", return_value=({"postgres"}, False)), mock.patch.object(tools, "command"):
            tools.restore(raw, self.work)
        prepared = (self.work / "prepared.sql").read_text()
        self.assertNotIn("CREATE ROLE postgres;", prepared)
        self.assertIn("ALTER ROLE postgres", prepared)

    def test_restore_failure_does_not_report_success(self):
        raw = self.write("SELECT missing_function();\n")
        output = io.StringIO()
        with mock.patch.object(tools, "preflight", return_value=(set(), False)), \
                mock.patch.object(tools, "command", side_effect=subprocess.CalledProcessError(3, "psql")), \
                contextlib.redirect_stdout(output), self.assertRaises(subprocess.CalledProcessError):
            tools.restore(raw, self.work)
        self.assertNotIn("Restore complete", output.getvalue())

    def test_bad_checksum_fails_before_preflight(self):
        path = self.work / "dump.sql.gz"
        with gzip.open(path, "wb") as output:
            output.write(tools.HEADER + json.dumps({"format_version": 1, "sql_sha256": "bad"}).encode() + b"\nSELECT 1;\n")
        with mock.patch.object(tools, "preflight") as preflight, self.assertRaisesRegex(ValueError, "checksum"):
            tools.restore(path, self.work)
        preflight.assert_not_called()

    def test_bad_gzip_and_multi_file_zip_are_rejected(self):
        bad = self.write("not gzip", "bad.sql.gz")
        with self.assertRaises(gzip.BadGzipFile):
            tools.unpack(bad, self.work)
        archive = self.work / "dump.zip"
        with zipfile.ZipFile(archive, "w") as output:
            output.writestr("one.sql", "SELECT 1;")
            output.writestr("two.sql", "SELECT 2;")
        with self.assertRaisesRegex(ValueError, "exactly one"):
            tools.unpack(archive, self.work)

    def run_backup(self, failure):
        fake_s3 = mock.Mock(args=["aws"], prefix="backup")
        calls = []

        def command(args, **kwargs):
            calls.append(args)
            if "--version" in args:
                return subprocess.CompletedProcess(args, 0, stdout="pg_dump 18.6")
            if args[0] == "pg_dump":
                if failure == "dump":
                    raise subprocess.CalledProcessError(1, args)
                kwargs["stdout"].write(b"SELECT 1;\n")
            if (args[0] == "openssl" and failure == "encryption") or (args[0] == "aws" and failure == "upload"):
                raise subprocess.CalledProcessError(1, args)
            return subprocess.CompletedProcess(args, 0, stdout="pg_dump 18.6")

        with mock.patch.object(tools, "S3", return_value=fake_s3), \
                mock.patch.object(tools, "describe_database", return_value={}), \
                mock.patch.object(tools, "command", side_effect=command):
            if failure == "compression":
                with mock.patch.object(tools.gzip, "open", side_effect=OSError("compression failed")), self.assertRaises(OSError):
                    tools.backup()
            else:
                if failure == "encryption":
                    os.environ["ENCRYPTION_PASSWORD"] = "test"
                with self.assertRaises(subprocess.CalledProcessError):
                    tools.backup()
        self.assertEqual(any(args[0] == "aws" for args in calls), failure == "upload")

    def test_dump_failure_never_uploads(self):
        self.run_backup("dump")

    def test_compression_failure_never_uploads(self):
        self.run_backup("compression")

    def test_encryption_failure_never_uploads(self):
        self.run_backup("encryption")

    def test_upload_failure_is_not_success(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.run_backup("upload")
        self.assertNotIn("Backup finished", output.getvalue())

    def test_help_cannot_be_uploaded_as_a_backup(self):
        os.environ["POSTGRES_EXTRA_OPTS"] = "--help"
        with mock.patch.object(tools, "S3"), mock.patch.object(tools, "command") as command, \
                self.assertRaisesRegex(ValueError, "help or version"):
            tools.backup()
        command.assert_not_called()

    def test_identifier_dollars_and_trailing_comments_preserve_passwords(self):
        raw = self.write("CREATE ROLE a$b$c; -- trailing comment\nALTER ROLE a$b$c PASSWORD 'source';\n")
        prepared = self.work / "prepared.sql"
        tools.prepare_roles(raw, prepared, {"a$b$c"})
        self.assertNotIn("source", prepared.read_text())
        self.assertIn("trailing comment", prepared.read_text())

    def test_legacy_bytes_survive_inplace_compaction(self):
        raw = self.work / "legacy.sql"
        payload = b"CREATE ROLE root; -- comment\nALTER ROLE root PASSWORD 'source';\nCOPY t FROM stdin;\n\xff\n\\.\n"
        raw.write_bytes(payload)
        declarations = {None: []}
        tools.prepare_roles(raw, raw, {"root"}, declarations)
        self.assertEqual(raw.read_bytes(), b"\n -- comment\n\n\nCOPY t FROM stdin;\n\xff\n\\.\n")

    def test_multiline_statement_is_joined_only_at_completion(self):
        raw = self.write("CREATE FUNCTION f() RETURNS text AS $$\n" + "x\n" * 10000 + "$$ LANGUAGE sql;\n")
        self.assertEqual("".join(chunk for _, chunk in tools.sql_chunks(raw)), raw.read_text())

    def test_link_port_uses_numeric_port(self):
        with mock.patch.dict(os.environ, {"POSTGRES_PORT": "tcp://127.0.0.1:5432", "POSTGRES_PORT_5432_TCP_PORT": "5433"}):
            self.assertEqual(tools.Postgres().args[3], "5433")

    def test_cleanup_requires_prefix_before_dumping(self):
        os.environ["DELETE_OLDER_THAN"] = "7 days ago"
        with mock.patch.object(tools, "S3", return_value=mock.Mock(prefix="")), \
                mock.patch.object(tools, "command") as command, self.assertRaisesRegex(ValueError, "non-empty"):
            tools.backup()
        command.assert_not_called()

    def test_cleanup_only_owns_matching_database_backup_keys(self):
        s3 = object.__new__(tools.S3)
        s3.prefix = "backup"
        for key in ["backup/20261029/app_2026-10-29_010203.sql.gz.enc", "backup/20261029/app_2026-10-29_010203_123456.tar.gz",
                    "backup/20261029/app_2026-10-29_010203_123456.tar.gz.enc", "backup/20261029/app_2026-10-29_010203_123456.tar"]:
            self.assertTrue(s3.owns_backup(key, "app"))
        for key in ["elsewhere/20261029/app_2026-10-29_010203.sql.gz", "backup/notes.sql.gz",
                    "backup/20261029/other_2026-10-29_010203.sql.gz", "backup/20261029/app_2026-10-29_010203.sql.gz.tmp"]:
            self.assertFalse(s3.owns_backup(key, "app"))

    def test_single_backup_does_not_parse_sql_or_force_utf8(self):
        pg = mock.Mock(database="app")
        raw = b"COPY t FROM stdin;\n\xff\n\\.\n"
        def command(args, **kwargs):
            if args[0] == "pg_dump" and "--version" not in args:
                kwargs["stdout"].write(raw)
            return subprocess.CompletedProcess(args, 0, stdout="pg_dump 18")
        with mock.patch.object(tools, "plan", side_effect=AssertionError("unnecessary scan")), \
                mock.patch.object(tools, "describe_database", return_value={}), \
                mock.patch.object(tools, "command", side_effect=command):
            compressed = tools.backup_sql(pg, self.work, ["pg_dump"])
        with gzip.open(compressed, "rb") as src:
            src.readline()
            self.assertEqual(src.read(), raw)

    def test_database_exclusion_patterns(self):
        for pattern, name in [('app*', 'app_one'), ('"Mixed"', 'Mixed'), ('app?', 'app1'), ('"a.b"', 'a.b')]:
            self.assertTrue(tools.database_pattern(pattern, name))
        self.assertFalse(tools.database_pattern('"Mixed"', 'mixed'))


APP_SQL = """\\restrict key
SET client_encoding = 'UTF8';
CREATE DATABASE app WITH TEMPLATE = template0 ENCODING = 'UTF8';
\\unrestrict key
\\connect app
\\restrict key
SET client_encoding = 'UTF8';
ALTER DATABASE app SET search_path TO public;
ALTER ROLE reader IN DATABASE app SET work_mem TO '8MB';
CREATE EXTENSION example;
CREATE FUNCTION f() RETURNS text AS $$ALTER DATABASE app SET x TO 1;$$ LANGUAGE sql;
COPY items (id) FROM stdin;
1
\\.
\\unrestrict key
"""


class BundleNameTests(unittest.TestCase):
    def test_names_stay_readable(self):
        used = set()
        self.assertEqual(tools.bundle_name("app", used), "databases/app.sql")
        self.assertEqual(tools.bundle_name("订单库", used), "databases/订单库.sql")
        self.assertEqual(tools.bundle_name("my.db-2_x", used), "databases/my.db-2_x.sql")

    def test_unsafe_characters_are_percent_encoded(self):
        used = set()
        self.assertEqual(tools.bundle_name("a/b c%~", used), "databases/a%2Fb%20c%25%7E.sql")
        self.assertEqual(tools.bundle_name("..", used), "databases/%2E..sql")

    def test_case_only_collisions_get_a_suffix(self):
        used = set()
        tools.bundle_name("app", used)
        self.assertEqual(tools.bundle_name("App", used), "databases/App~2.sql")
        self.assertEqual(tools.bundle_name("APP", used), "databases/APP~3.sql")


class BundleTests(TempCase):
    def bundle(self, corrupt=False, complete=True, sql=APP_SQL):
        source = self.work / "source"
        (source / "databases").mkdir(parents=True, exist_ok=True)
        files = {"databases/app.sql": sql, "roles.sql": "CREATE ROLE business;\n",
                 "tablespaces.sql": "-- no custom tablespaces\n"}
        for name, text in files.items():
            (source / name).write_text(text)
        manifest = {"format_version": 3, "database": "all", "databases": {"app": {
            "file": "databases/app.sql", "sha256": tools.file_hash(source / "databases/app.sql")}},
            "roles": {"file": "roles.sql", "sha256": tools.file_hash(source / "roles.sql")},
            "tablespaces": {"file": "tablespaces.sql", "sha256": tools.file_hash(source / "tablespaces.sql")}}
        (source / "manifest.json").write_text(json.dumps(manifest))
        names = [*files, "manifest.json"]
        if complete:
            (source / "COMPLETE").write_text(tools.file_hash(source / "manifest.json"))
            names.append("COMPLETE")
        if corrupt:
            (source / "databases/app.sql").write_text("damaged")
        archive = self.work / "all.tar.gz"
        with tarfile.open(archive, "w:gz") as output:
            for name in names:
                output.add(source / name, arcname=name)
        return archive

    def test_corrupt_or_incomplete_bundle_never_connects(self):
        for corrupt, complete in [(True, True), (False, False)]:
            with self.subTest(corrupt=corrupt), tempfile.TemporaryDirectory() as temp:
                archive = self.bundle(corrupt, complete)
                with mock.patch.object(tools, "Postgres") as pg, self.assertRaisesRegex(ValueError, "checksum|Incomplete"):
                    tools.restore_bundle(archive, Path(temp))
                pg.assert_not_called()

    def test_archive_path_traversal_is_rejected(self):
        for name in ["../outside.sql", "databases/../outside.sql", "databases/.hidden.sql"]:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                archive = self.work / "all.tar.gz"
                with tarfile.open(archive, "w:gz") as output:
                    output.add(self.write("bad"), arcname=name)
                with self.assertRaisesRegex(ValueError, "Invalid"):
                    tools.read_bundle(archive, Path(temp))
                self.assertFalse((Path(temp).parent / "outside.sql").exists())

    def restore_bundle(self, existing, restore_roles):
        archive = self.bundle()
        os.environ["RESTORE_ROLES"] = "true" if restore_roles else "false"
        pg = mock.Mock(database="postgres", args=["-h", "localhost"])
        pg.query.return_value = ["postgres", "app"] if existing else ["postgres"]
        pg.psql.side_effect = lambda database: ["psql", database]
        calls = []

        def command(args, **kwargs):
            # Snapshot scripts when psql runs them; prepared files may be reused.
            script = Path(args[args.index("-f") + 1]).read_text() if "-f" in args else None
            calls.append((args, script))

        with mock.patch.object(tools, "Postgres", return_value=pg), \
                mock.patch.object(tools, "preflight", return_value=({"postgres"}, True)) as check, \
                mock.patch.object(tools, "command", side_effect=command):
            tools.restore_bundle(archive, self.work)
        self.assertEqual(check.call_args.args[3], {"app": ["example"]})
        creations = [args[-1] for args, _ in calls if "-c" in args]
        roles = [script for args, script in calls if args[1] == "postgres" and script and "business" in script]
        bodies = [script for args, script in calls if args[1] == "app" and "-f" in args]
        self.assertEqual(len(bodies), 1)
        return creations, roles, bodies[0]

    def test_new_database_is_created_then_loaded_without_reconnecting(self):
        creations, roles, body = self.restore_bundle(existing=False, restore_roles=False)
        self.assertEqual(creations, ["CREATE DATABASE app WITH TEMPLATE = template0 ENCODING = 'UTF8';"])
        self.assertEqual(roles, [])
        self.assertNotIn("CREATE DATABASE", body)
        self.assertNotIn("\\connect", body)
        self.assertIn("ALTER DATABASE app SET search_path", body)
        self.assertNotIn("ALTER ROLE reader", body)
        self.assertIn("$$ALTER DATABASE app SET x TO 1;$$", body)
        self.assertIn("COPY items (id) FROM stdin;\n1\n\\.\n", body)
        self.assertIn("\\restrict key", body)

    def test_role_settings_follow_restored_roles(self):
        creations, roles, body = self.restore_bundle(existing=False, restore_roles=True)
        self.assertEqual(len(creations), 1)
        self.assertEqual(len(roles), 1)
        self.assertIn("ALTER ROLE reader IN DATABASE app", body)

    def test_existing_database_keeps_its_own_settings(self):
        creations, roles, body = self.restore_bundle(existing=True, restore_roles=True)
        self.assertEqual(creations, [])
        self.assertEqual(len(roles), 1)
        self.assertNotIn("ALTER DATABASE app SET search_path", body)
        self.assertNotIn("ALTER ROLE reader", body)
        self.assertIn("CREATE EXTENSION example;", body)

    def test_connection_to_another_database_is_rejected(self):
        archive = self.bundle(sql=APP_SQL.replace("\\connect app", "\\connect other"))
        pg = mock.Mock(database="postgres", args=[])
        pg.query.return_value = ["postgres"]
        with mock.patch.object(tools, "Postgres", return_value=pg), mock.patch.object(tools, "command") as command, \
                self.assertRaisesRegex(ValueError, "connection"):
            tools.restore_bundle(archive, self.work)
        command.assert_not_called()

    def test_unknown_database_never_connects(self):
        os.environ["RESTORE_DATABASE"] = "unknown"
        with mock.patch.object(tools, "command") as command, self.assertRaisesRegex(ValueError, "not in this backup"):
            tools.restore_bundle(self.bundle(), self.work)
        command.assert_not_called()

    def test_previous_tar_bundles_are_rejected_before_connecting(self):
        for name in ("all.tar", "all.tar.enc"):
            with self.subTest(name=name), mock.patch.object(tools, "Postgres") as pg, \
                    self.assertRaisesRegex(ValueError, "no longer supported"):
                tools.restore(self.write("old", name), self.work)
            pg.assert_not_called()

    def test_s3_selects_latest_sql_bundle_and_retains_encrypted_suffix(self):
        s3 = mock.Mock(args=["aws"], prefix="backup")
        s3.objects.return_value = [
            {"Key": "backup/old.sql.gz", "LastModified": "2026-10-28T00:00:00Z"},
            {"Key": "backup/new.tar.gz.enc", "LastModified": "2026-10-29T00:00:00Z"},
            {"Key": "backup/previous-format.tar", "LastModified": "2026-10-30T00:00:00Z"},
            {"Key": "backup/incomplete.tmp", "LastModified": "2026-10-30T00:00:00Z"}]
        with mock.patch.object(tools, "S3", return_value=s3), mock.patch.object(tools, "command"), \
                mock.patch.object(tools, "restore") as restore:
            tools.restore_s3()
        self.assertEqual(restore.call_args.args[0].name, "new.tar.gz.enc")

    def test_all_database_backup_uploads_readable_sql_bundle(self):
        os.environ.update(POSTGRES_DATABASE="all", POSTGRES_EXTRA_OPTS="auto")
        pg = mock.Mock(database="all", args=[])
        pg.query.return_value = ["app", "a/b"]
        s3 = mock.Mock(args=["aws"], prefix="backup")
        s3.uri.side_effect = lambda key: key
        uploaded = self.work / "uploaded"
        calls = []

        def command(args, **kwargs):
            calls.append(args)
            if "--version" in args:
                return subprocess.CompletedProcess(args, 0, stdout="pg_dump 18")
            if args[0] == "pg_dump":
                Path(args[args.index("--file") + 1]).write_text("CREATE DATABASE x;\n-- " + args[-1] + "\n")
            elif args[0] == "pg_dumpall":
                kwargs["stdout"].write(b"-- globals\n")
            elif args[0] == "aws":
                shutil.copy(args[3], uploaded)
            return subprocess.CompletedProcess(args, 0)

        with mock.patch.object(tools, "Postgres", return_value=pg), mock.patch.object(tools, "S3", return_value=s3), \
                mock.patch.object(tools, "describe_database", return_value={}), \
                mock.patch.object(tools, "command", side_effect=command):
            tools.backup()
        key = next(args[4] for args in calls if args[0] == "aws")
        self.assertRegex(key, r"^backup/[0-9]{8}/all_.*\.tar\.gz$")
        with tarfile.open(uploaded, "r:gz") as archive:
            self.assertEqual(sorted(archive.getnames()), sorted([
                "databases/app.sql", "databases/a%2Fb.sql", "roles.sql", "tablespaces.sql", "manifest.json", "COMPLETE"]))
            manifest = json.load(archive.extractfile("manifest.json"))
            self.assertTrue(archive.extractfile("databases/app.sql").read().startswith(b"CREATE DATABASE"))
        self.assertEqual(manifest["format_version"], 3)
        self.assertEqual(manifest["databases"]["a/b"]["file"], "databases/a%2Fb.sql")
        dumps = [args for args in calls if args[0] == "pg_dump" and "--version" not in args]
        self.assertEqual(len(dumps), 2)
        for args in dumps:
            for option in ["--create", "--no-owner", "--no-acl", "--no-tablespaces"]:
                self.assertIn(option, args)
            self.assertFalse(any(arg.startswith("--format") for arg in args))

    def test_legacy_sql_selection_is_rejected_before_connecting(self):
        os.environ["RESTORE_DATABASE"] = "app"
        with mock.patch.object(tools, "Postgres") as pg, self.assertRaisesRegex(ValueError, "selection requires"):
            tools.restore(self.write("CREATE DATABASE app;"), self.work)
        pg.assert_not_called()

    def test_all_database_failure_never_uploads(self):
        os.environ["POSTGRES_DATABASE"] = "all"
        pg = mock.Mock(database="all", args=[])
        pg.query.return_value = ["first", "second"]
        calls = []

        def command(args, **kwargs):
            calls.append(args)
            if "--version" in args:
                return subprocess.CompletedProcess(args, 0, stdout="pg_dump 18")
            if args[0] == "pg_dump":
                if "second" in args[-1]:
                    raise subprocess.CalledProcessError(1, args)
                Path(args[args.index("--file") + 1]).write_bytes(b"archive")

        with mock.patch.object(tools, "Postgres", return_value=pg), mock.patch.object(tools, "S3"), \
                mock.patch.object(tools, "describe_database", return_value={}), \
                mock.patch.object(tools, "command", side_effect=command), self.assertRaises(subprocess.CalledProcessError):
            tools.backup()
        self.assertEqual(len([args for args in calls if args[0] == "pg_dump" and "--version" not in args]), 2)
        self.assertFalse(any(args[0] == "aws" for args in calls))


class PreflightTests(TempCase):
    def check(self, declared, available, source_version=None, installed=None, target_major=18):
        pg = mock.Mock(database="restore_test")
        pg.query.side_effect = [available, ["restore_test"], ["postgres"]]
        target = {"server_version_num": target_major * 10000, "extensions": installed or [],
                  "shared_preload_libraries": ""}
        metadata = None
        if source_version:
            metadata = {"database": "source", "databases": {"source": {
                "server_version_num": 180006, "shared_preload_libraries": "",
                "extensions": [{"name": "pg_search", "version": source_version}],
            }}}
        raw = self.write("\n".join(f"CREATE EXTENSION IF NOT EXISTS {name};" for name in declared))
        with mock.patch.object(tools, "describe_database", return_value=target):
            return tools.preflight(pg, raw, metadata)

    def test_missing_extension(self):
        with self.assertRaisesRegex(ValueError, "unavailable"):
            self.check(["pg_search"], [])

    def test_legacy_dependency_order_fails_before_restore(self):
        available = [{"name": "pg_search", "version": "0.26", "requires": ["vector"]},
                     {"name": "vector", "version": "0.8", "requires": None}]
        with self.assertRaisesRegex(ValueError, "requires 'vector'"):
            self.check(["pg_search", "vector"], available)
        self.check(["vector", "pg_search"], available)

    def test_version_mismatch(self):
        with self.assertRaisesRegex(ValueError, "version mismatch"):
            self.check(["pg_search"], [{"name": "pg_search", "version": "0.26", "requires": None}], "0.24")

    def test_server_major_mismatch(self):
        with self.assertRaisesRegex(ValueError, "major version"):
            self.check(["pg_search"], [], "0.24", target_major=17)

    def test_installed_version_takes_precedence_over_new_default(self):
        self.check(["pg_search"], [{"name": "pg_search", "version": "0.26", "requires": ["vector"]}],
                   "0.24", [{"name": "pg_search", "version": "0.24"}])

    def test_newer_server_is_allowed(self):
        self.check([], [], "0.24", target_major=19)

    def test_extension_version_override_still_checks_dependencies(self):
        with mock.patch.dict(os.environ, {"RESTORE_ALLOW_EXTENSION_VERSION_MISMATCH": "true"}):
            self.check(["pg_search"], [{"name": "pg_search", "version": "0.26", "requires": None}], "0.24")
            with self.assertRaisesRegex(ValueError, "requires"):
                self.check(["pg_search"], [{"name": "pg_search", "version": "0.26", "requires": ["vector"]}], "0.24")


if __name__ == "__main__":
    unittest.main()
