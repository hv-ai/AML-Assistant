from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import accounts as a

class AccountTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.patcher=patch.object(a,'DB',Path(self.temp.name)/'accounts.sqlite3');self.patcher.start()
    def tearDown(self):self.patcher.stop();self.temp.cleanup()
    def test_password_is_hashed_and_session_is_resolved(self):
        user,token=a.register('alice','test-password-123')
        self.assertEqual(a.current_user(token)['id'],user['id'])
        with a.db()as c:
            row=c.execute('SELECT password_hash FROM users').fetchone()
            self.assertNotEqual(row[0],'test-password-123')
            self.assertNotEqual(c.execute('SELECT token_hash FROM sessions').fetchone()[0],token)
    def test_history_isolated_by_account_even_for_same_record_id(self):
        alice,_=a.register('alice','test-password-123');bob,_=a.register('bobby','different-password-123')
        a.save_work(alice['id'],{'id':'record-123','question':'CDD review','notes':'Alice only','answer':None})
        self.assertEqual(a.history(bob['id']),[])
        a.save_work(bob['id'],{'id':'record-123','question':'Bobs brief','notes':'Bob only','answer':None})
        self.assertEqual(a.history(alice['id'])[0]['notes'],'Alice only')
    def test_sign_out_invalidates_token(self):
        user,token=a.register('alice','test-password-123');a.logout(token)
        self.assertIsNone(a.current_user(token))
    def test_login_restores_history(self):
        user,token=a.register('alice','test-password-123')
        a.save_work(user['id'],{'id':'record-123','question':'CDD','notes':'saved','answer':None});a.logout(token)
        user2,new_token=a.login('ALICE','test-password-123')
        self.assertEqual(a.history(user2['id'])[0]['notes'],'saved')
    def test_failed_login_is_rate_limited(self):
        a.register('alice','test-password-123')
        for _ in range(5):
            with self.assertRaises(a.AccountError):a.login('alice','incorrect-password')
        with self.assertRaisesRegex(a.AccountError,'Too many'):a.login('alice','test-password-123')
    def test_expired_session_is_rejected(self):
        user,token=a.register('alice','test-password-123')
        with a.db()as c:c.execute('UPDATE sessions SET expires=0')
        self.assertIsNone(a.current_user(token))
    def test_short_password_rejected(self):
        with self.assertRaises(a.AccountError):a.register('alice','short')

if __name__=='__main__':unittest.main()
