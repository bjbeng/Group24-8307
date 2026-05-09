import os, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
os.environ['CHROMA_DB_PATH'] = './data/chroma_db'
from dotenv import load_dotenv
load_dotenv('.env', override=False)
print('URL:', os.environ.get('LLM_BASE_URL'), flush=True)
from src.standards_lib.ingest_chroma import ingest_all
print('starting ingest...', flush=True)
results = ingest_all(force=True)
print('done', flush=True)
for k, v in results.items():
    print(f'  {k}: {v} chunks', flush=True)