import base64
import hashlib
import hmac
import unittest
from unittest.mock import patch

from app.roles import TABLE_PRIVILEGES, RoleNames, generate_password, scram_verifier

FORBIDDEN_FOR_APP = {"TRUNCATE", "DROP", "ALTER", "REFERENCES", "TRIGGER"}


class RoleNamesTests(unittest.TestCase):
    def test_prefix_builds_all_names(self) -> None:
        names = RoleNames.with_prefix("t1")
        self.assertEqual(("t1_owner", "t1_app", "t1_ro", "t1_test"), (names.owner, names.app, names.ro, names.test))

    def test_defaults_and_environment(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual("boxoffice_app", RoleNames.from_env().app)
        with patch.dict("os.environ", {"DB_USER": "x", "DB_RO_USER": "lettore"}, clear=True):
            names = RoleNames.from_env()
        self.assertEqual(("x", "lettore"), (names.app, names.ro))


class PasswordTests(unittest.TestCase):
    def test_generated_passwords_are_long_and_different(self) -> None:
        first, second = generate_password(), generate_password()
        self.assertNotEqual(first, second)
        self.assertGreaterEqual(len(first), 40)

    def test_scram_verifier_has_the_postgres_format_and_hides_the_password(self) -> None:
        verifier = scram_verifier("segreto-di-prova")
        self.assertNotIn("segreto", verifier)
        scheme, rest = verifier.split("$", 1)
        iterations_salt, keys = rest.split("$", 1)
        iterations, salt_b64 = iterations_salt.split(":")
        stored_b64, server_b64 = keys.split(":")

        self.assertEqual(("SCRAM-SHA-256", "4096"), (scheme, iterations))
        # ricalcolo indipendente delle chiavi a partire da password e sale: devono coincidere
        salted = hashlib.pbkdf2_hmac("sha256", b"segreto-di-prova", base64.b64decode(salt_b64), 4096)
        client_key = hmac.new(salted, b"Client Key", hashlib.sha256).digest()
        self.assertEqual(hashlib.sha256(client_key).digest(), base64.b64decode(stored_b64))
        self.assertEqual(hmac.new(salted, b"Server Key", hashlib.sha256).digest(), base64.b64decode(server_b64))

    def test_scram_verifier_uses_a_fresh_salt(self) -> None:
        self.assertNotEqual(scram_verifier("x"), scram_verifier("x"))


class TablePrivilegesTests(unittest.TestCase):
    def test_app_never_gets_ddl_like_privileges(self) -> None:
        for table, (app, ro) in TABLE_PRIVILEGES.items():
            self.assertFalse(FORBIDDEN_FOR_APP & set(app), table)
            self.assertEqual(("SELECT",), ro, f"{table}: il ruolo ro deve essere di sola lettura")

    def test_app_can_only_delete_where_the_code_needs_it(self) -> None:
        with_delete = {t for t, (app, _) in TABLE_PRIVILEGES.items() if "DELETE" in app}
        self.assertEqual({"source_movies", "match_candidates"}, with_delete)

    def test_history_and_lineage_tables_are_not_deletable_or_updatable_by_the_app_when_not_needed(self) -> None:
        self.assertEqual(("SELECT", "INSERT"), TABLE_PRIVILEGES["raw_snapshots"][0])
        self.assertEqual(("SELECT",), TABLE_PRIVILEGES["schema_migrations"][0])


if __name__ == "__main__":
    unittest.main()
