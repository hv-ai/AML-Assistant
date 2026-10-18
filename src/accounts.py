"""Local prototype accounts and per-user research history. Not a hosted identity service."""
from contextlib import contextmanager
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
from aml_research import ROOT

DB = ROOT / '.runtime/accounts.sqlite3'
SESSION_SECONDS = 7 * 24 * 3600

class AccountError(ValueError):
    pass

@contextmanager
def db():
    DB.parent.mkdir(exist_ok=True)
    connection = sqlite3.connect(DB, timeout=10)
    os.chmod(DB, 0o600)
    connection.row_factory = sqlite3.Row
    try:
        connection.executescript('''
        CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, salt TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS history(user_id TEXT NOT NULL, id TEXT NOT NULL, payload TEXT NOT NULL, updated REAL NOT NULL, PRIMARY KEY(user_id,id));
        CREATE TABLE IF NOT EXISTS login_attempts(username TEXT NOT NULL, attempted REAL NOT NULL);
        ''')
        yield connection
        connection.commit()
    finally:
        connection.close()

def credentials(username,password):
    if not isinstance(username,str) or not re.fullmatch(r'[a-zA-Z0-9_.-]{3,40}',username):
        raise AccountError('Use a username of 3–40 letters, numbers, dots, underscores or hyphens.')
    if not isinstance(password,str) or not 12 <= len(password) <= 256:
        raise AccountError('Use a password between 12 and 256 characters.')
    return username.lower(),password

def digest(password,salt):
    return hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),n=16384,r=8,p=1).hex()

def token_digest(token):
    return hashlib.sha256(token.encode()).hexdigest()

def create_session(connection,user_id):
    token=secrets.token_urlsafe(32)
    connection.execute('DELETE FROM sessions WHERE expires < ?',(time.time(),))
    connection.execute('INSERT INTO sessions VALUES (?,?,?)',(token_digest(token),user_id,time.time()+SESSION_SECONDS))
    return token

def register(username,password):
    username,password=credentials(username,password)
    salt=secrets.token_hex(16);user_id=secrets.token_hex(16)
    with db() as c:
        if c.execute('SELECT count(*) FROM users').fetchone()[0]>=100:
            raise AccountError('Local account capacity reached.')
        try:c.execute('INSERT INTO users VALUES (?,?,?,?)',(user_id,username,digest(password,salt),salt))
        except sqlite3.IntegrityError:raise AccountError('That username is unavailable.') from None
        return {'id':user_id,'username':username},create_session(c,user_id)

def login(username,password):
    username,password=credentials(username,password)
    failed=False
    with db()as c:
        now=time.time()
        c.execute('DELETE FROM login_attempts WHERE attempted < ?',(now-900,))
        total=c.execute('SELECT count(*) FROM login_attempts').fetchone()[0]
        if total>=20 or c.execute('SELECT count(*) FROM login_attempts WHERE username=?',(username,)).fetchone()[0]>=5:
            raise AccountError('Too many sign-in attempts. Try again in 15 minutes.')
        row=c.execute('SELECT * FROM users WHERE username=?',(username,)).fetchone()
        # Use the same password derivation when a username is unknown.
        actual=digest(password,row['salt'] if row else '00'*16)
        if row is None or not hmac.compare_digest(actual,row['password_hash']):
            c.execute('INSERT INTO login_attempts VALUES (?,?)',(username,now));failed=True
        else:
            c.execute('DELETE FROM login_attempts WHERE username=?',(username,))
            result=({'id':row['id'],'username':row['username']},create_session(c,row['id']))
    if failed:raise AccountError('Username or password is incorrect.')
    return result

def current_user(token):
    if not token or len(token)>200:return None
    with db()as c:
        row=c.execute('SELECT users.id,users.username FROM sessions JOIN users ON users.id=sessions.user_id WHERE token_hash=? AND expires>?',(token_digest(token),time.time())).fetchone()
        return dict(row) if row else None

def logout(token):
    if token:
        with db()as c:c.execute('DELETE FROM sessions WHERE token_hash=?',(token_digest(token),))

def save_work(user_id,work):
    if not isinstance(work,dict) or not re.fullmatch(r'[a-zA-Z0-9-]{8,64}',str(work.get('id',''))):
        raise AccountError('Invalid research record.')
    if not isinstance(work.get('question',''),str) or len(work.get('question',''))>2000 or not isinstance(work.get('notes',''),str) or len(work.get('notes',''))>20000:
        raise AccountError('Research record exceeds text limits.')
    answer=work.get('answer')
    if answer is not None and (not isinstance(answer,dict) or not isinstance(answer.get('evidence'),list) or not isinstance(answer.get('claims',[]),list)):
        raise AccountError('Invalid saved answer.')
    clean={k:work.get(k) for k in ('id','question','notes','answer')}
    clean['updatedAt']=int(time.time()*1000)
    payload=json.dumps(clean)
    if len(payload.encode())>180000:raise AccountError('Research record is too large.')
    with db()as c:
        c.execute('INSERT INTO history VALUES (?,?,?,?) ON CONFLICT(user_id,id) DO UPDATE SET payload=excluded.payload,updated=excluded.updated',(user_id,clean['id'],payload,time.time()))
    return clean

def history(user_id):
    with db()as c:
        return [json.loads(row['payload']) for row in c.execute('SELECT payload FROM history WHERE user_id=? ORDER BY updated DESC LIMIT 50',(user_id,))]
