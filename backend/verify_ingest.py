"""快速验证：先只 embed不进 summary，确认链路通后再加 summary。"""
import os, sys, logging, json
logging.basicConfig(level=logging.INFO, format='%(name)s %(levelname)s %(message)s', encoding='utf-8', errors='replace')
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

os.environ['CHROMA_DB_PATH'] = './data/chroma_db'
from dotenv import load_dotenv; load_dotenv('.env', override=False)
print('BASE_URL:', os.environ.get('LLM_BASE_URL'), flush=True)

from src.standards_lib.embedder import get_embedder
print('loading embedder...', flush=True)
e = get_embedder()
print('embedder ready, dim=', e.dimension, flush=True)

# 快速测试 LLM
from src.llm import Message
from src.llm.factory import build_provider
from src.config import get_default_config
cfg = get_default_config()
p = build_provider(cfg)
print('provider ready', flush=True)

prompt = '只用中文回复"OK"'
r = p.call_text([Message(role='user', content=prompt)], model='deepseek-v3.2', temperature=0, max_tokens=50)
print('LLM response:', r[:50], flush=True)

print('ALL OK - proceed with ingest', flush=True)