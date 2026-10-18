"""Store Nebius settings locally without echoing the key or placing it in history."""
from getpass import getpass
import argparse
from pathlib import Path
import os

path = Path(__file__).resolve().parent / '.env'
if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--pinecone',action='store_true',help='Configure Pinecone without changing the Nebius key')
    args=parser.parse_args()
    values = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                k, v = line.split('=', 1)
                values[k.strip()] = v.strip()
    setting='PINECONE_API_KEY' if args.pinecone else 'NEBIUS_API_KEY'
    key = getpass('Paste your '+('Pinecone' if args.pinecone else 'Nebius Token Factory')+' API key (hidden; Enter keeps existing): ').strip()
    if key:
        if any(c.isspace() for c in key):raise SystemExit('Key must not contain whitespace. Nothing saved.')
        values[setting]=key
    if not values.get(setting):raise SystemExit('No key supplied. Nothing saved.')
    if args.pinecone:
        values.setdefault('PINECONE_INDEX','aml-research')
        values.setdefault('PINECONE_CLOUD','aws')
        values.setdefault('PINECONE_REGION','us-east-1')
    values.setdefault('NEBIUS_MODEL', 'Qwen/Qwen3-30B-A3B-Instruct-2507')
    values.setdefault('NEBIUS_EMBEDDING_MODEL','Qwen/Qwen3-Embedding-8B')
    values.setdefault('NEBIUS_BASE_URL', 'https://api.tokenfactory.nebius.com/v1')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write('# Local settings. Ignored by Git. Never share this file.\n')
        for k, v in values.items():
            f.write(f'{k}={v}\n')
    print('Saved local .env with owner-only permissions. No API request made.')
    print('Start with: python3 app.py')
