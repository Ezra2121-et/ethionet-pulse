import unittest

from app.web import hash_password, verify_password


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
