import unittest

from starlette.requests import Request

from app.web import _csrf_ok, _csrf_token, hash_password, verify_password


class PasswordHashTests(unittest.TestCase):
    def test_password_is_stored_as_a_salted_hash(self):
        password = "correct-horse-battery-staple"
        first = hash_password(password)
        second = hash_password(password)

        self.assertNotEqual(first, password)
        self.assertNotEqual(first, second)
        self.assertTrue(first.startswith("scrypt$"))
        self.assertTrue(verify_password(password, first))
        self.assertTrue(verify_password(password, second))

    def test_wrong_password_is_rejected(self):
        stored = hash_password("another-long-password")
        self.assertFalse(verify_password("wrong-password", stored))
        self.assertFalse(verify_password("any-password", None))
        self.assertFalse(verify_password("any-password", "not-a-valid-hash"))


    def test_csrf_token_is_required_and_session_bound(self):
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "headers": [],
            "client": ("test-client", 1234),
            "server": ("test-server", 80),
            "session": {},
        }
        request = Request(scope)
        token = _csrf_token(request)

        self.assertTrue(token)
        self.assertTrue(_csrf_ok(request, token))
        self.assertFalse(_csrf_ok(request, "wrong-token"))
        self.assertFalse(_csrf_ok(request, ""))


if __name__ == "__main__":
    unittest.main(verbosity=2)
