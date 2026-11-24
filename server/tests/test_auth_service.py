"""程序说明：验证单一访问码与短期会话行为。"""
import sys
import unittest
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIR))

from services.auth_service import AccessCodeAuth


class AccessCodeAuthTests(unittest.TestCase):
    def setUp(self):
        self.auth = AccessCodeAuth(access_code="test-access-code")

    def test_access_code_comparison(self):
        self.assertTrue(self.auth.verify_access_code("test-access-code"))
        self.assertFalse(self.auth.verify_access_code("wrong-code"))
        self.assertFalse(self.auth.verify_access_code(""))

    def test_session_is_valid_until_revoked(self):
        token = self.auth.create_session()
        self.assertTrue(self.auth.is_valid_session(token))
        self.auth.revoke_session(token)
        self.assertFalse(self.auth.is_valid_session(token))


if __name__ == "__main__":
    unittest.main()
