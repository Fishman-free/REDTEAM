"""Safe OpenAI-compatible proposal adapter; never executes model output."""
import json, os, re, urllib.request, urllib.error
from pathlib import Path

PROMPT_VERSION = "payment-agent-system-v1"
_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "payment_agent_system_v1.txt"
def load_system_prompt():
    return _PROMPT_PATH.read_text(encoding="utf-8-sig")

_MAX_BODY = 65536
_PAY = re.compile(r'^PAY (INV-[0-9]{3}) TO ([a-z][a-z0-9_-]{0,31}) AMOUNT ([0-9]{1,6})$', re.I)

def request_proposal(text, transport=None, timeout=5):
    base, key, model = (os.getenv(k, '').strip() for k in ('REDTEAM_LLM_BASE_URL','REDTEAM_LLM_API_KEY','REDTEAM_LLM_MODEL'))
    # Network is opt-in, regardless of endpoint configuration.
    if os.getenv('REDTEAM_LLM_ENABLED') != '1' and transport is None:
        return None, {'adapter':'deterministic','prompt_version':PROMPT_VERSION,'fallback':True,'error':'disabled'}
    if not (base and key and model): return None, {'adapter':'deterministic','prompt_version':PROMPT_VERSION,'fallback':True,'error':'missing_config'}
    payload = json.dumps({'model':model,'messages':[{'role':'system','content':load_system_prompt()},{'role':'user','content':text[:8000]}]}).encode()
    try:
        if transport:
            raw = transport(base.rstrip('/')+'/chat/completions', payload, {'Authorization':'Bearer '+key,'Content-Type':'application/json'}, timeout)
        else:
            req=urllib.request.Request(base.rstrip('/')+'/chat/completions', data=payload, headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                if int(r.headers.get('Content-Length','0') or 0)>_MAX_BODY: raise ValueError('body_limit')
                raw=r.read(_MAX_BODY+1)
        if len(raw)>_MAX_BODY: raise ValueError('body_limit')
        obj=json.loads(raw.decode() if isinstance(raw,(bytes,bytearray)) else raw)
        content=obj['choices'][0]['message']['content']
        if not isinstance(content,str) or len(content)>200: raise ValueError('schema')
        line=content.strip()
        m=_PAY.fullmatch(line)
        if not m: raise ValueError('parse')
        return {'invoice':m.group(1).upper(),'recipient':m.group(2).lower(),'amount':int(m.group(3))},{'adapter':'openai-compatible','prompt_version':PROMPT_VERSION,'fallback':False,'error':None}
    except Exception as e:
        kind='http' if isinstance(e,urllib.error.HTTPError) else ('network' if isinstance(e,urllib.error.URLError) else str(e))
        return None, {'adapter':'openai-compatible','prompt_version':PROMPT_VERSION,'fallback':True,'error':kind[:40]}
