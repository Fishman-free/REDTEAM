import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .agents import decide_with_meta, resolve_llm
from .policy import evaluate
from .scenario import (EVIDENCE_VERSION, INITIAL_TOKENS, MAX_TRANSFER,
                       RECIPIENT_ALLOWLIST, SCENARIO_VERSION)


class Problem(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path, *, backend=None, adapter=None):
        if backend not in (None, 'mock', 'openai-compatible'):
            raise Problem('backend must be mock or openai-compatible')
        self.path = str(Path(path).resolve())
        self.backend = backend
        self.adapter = adapter
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript(f'''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, mode TEXT NOT NULL, created TEXT NOT NULL,
                    parent TEXT, scenario TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS accounts (
                    run TEXT NOT NULL REFERENCES runs(id), name TEXT NOT NULL,
                    balance INTEGER NOT NULL CHECK(balance >= 0), PRIMARY KEY(run,name));
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY, run TEXT NOT NULL REFERENCES runs(id),
                    request_key TEXT NOT NULL, text TEXT NOT NULL, created TEXT NOT NULL,
                    result TEXT NOT NULL, UNIQUE(run, request_key));
                CREATE TABLE IF NOT EXISTS transfers (
                    id INTEGER PRIMARY KEY, run TEXT NOT NULL REFERENCES runs(id),
                    operation TEXT NOT NULL, invoice TEXT NOT NULL, recipient TEXT NOT NULL,
                    amount INTEGER NOT NULL CHECK(amount > 0 AND amount <= {MAX_TRANSFER}),
                    created TEXT NOT NULL, violations TEXT NOT NULL, UNIQUE(run,operation));
            ''')
            # Additive migration preserves existing runs and retry result bytes.
            columns = {row['name'] for row in db.execute('PRAGMA table_info(runs)')}
            if 'evidence_version' not in columns:
                db.execute("ALTER TABLE runs ADD COLUMN evidence_version TEXT NOT NULL DEFAULT 'legacy'")
            if 'backend' not in columns:
                db.execute("ALTER TABLE runs ADD COLUMN backend TEXT NOT NULL DEFAULT 'unknown'")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def create(self, mode, parent=None):
        if mode not in ('vulnerable', 'hardened'):
            raise Problem('mode must be vulnerable or hardened')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT COUNT(*) FROM runs').fetchone()[0] >= 1000:
                raise Problem('Experiment database limit reached (1000 runs). Use a new database.', 409)
            run = uuid.uuid4().hex
            backend_name = resolve_llm(self.adapter, self.backend).name
            db.execute('INSERT INTO runs(id,mode,created,parent,scenario,evidence_version,backend) VALUES (?,?,?,?,?,?,?)',
                       (run, mode, now(), parent, SCENARIO_VERSION, EVIDENCE_VERSION, backend_name))
            db.executemany('INSERT INTO accounts VALUES (?,?,?)',
                           [(run, 'treasury', INITIAL_TOKENS)] +
                           [(run, recipient, 0) for recipient in sorted(RECIPIENT_ALLOWLIST)])
        return self.snapshot(run)

    @staticmethod
    def require_run(db, run):
        row = db.execute('SELECT * FROM runs WHERE id=?', (run,)).fetchone()
        if row is None:
            raise Problem('Run not found', 404)
        return dict(row)

    @staticmethod
    def execute(db, run, operation, proposal):
        """Local ledger authority only; it intentionally does not consult policy."""
        recipient, amount = proposal['recipient'], proposal['amount']
        if recipient not in RECIPIENT_ALLOWLIST:
            raise Problem('Executor boundary: only experimental merchant/participant accounts exist')
        if type(amount) is not int or not 1 <= amount <= MAX_TRANSFER:
            raise Problem(f'Executor boundary: transfer must be 1..{MAX_TRANSFER} experimental tokens')
        debit = db.execute('UPDATE accounts SET balance=balance-? WHERE run=? AND name=? AND balance>=?',
                           (amount, run, 'treasury', amount))
        if debit.rowcount != 1:
            raise Problem('Executor boundary: insufficient treasury balance')
        db.execute('UPDATE accounts SET balance=balance+? WHERE run=? AND name=?',
                   (amount, run, recipient))
        cursor = db.execute('INSERT INTO transfers(run,operation,invoice,recipient,amount,created,violations) VALUES (?,?,?,?,?,?,?)',
                            (run, operation, proposal['invoice'], recipient, amount, now(), '[]'))
        return cursor.lastrowid

    def submit(self, run, key, text):
        if not isinstance(key, str) or not 1 <= len(key) <= 100:
            raise Problem('request_key must be a string of 1..100 characters')
        if not isinstance(text, str) or not 1 <= len(text) <= 8000:
            raise Problem('text must be a string of 1..8000 characters')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            record = self.require_run(db, run)
            old = db.execute('SELECT text,result FROM messages WHERE run=? AND request_key=?',
                             (run, key)).fetchone()
            if old:
                if old['text'] != text:
                    raise Problem('Idempotency key already used with different text', 409)
                return json.loads(old['result'])
            message_count = db.execute('SELECT COUNT(*) FROM messages WHERE run=?', (run,)).fetchone()[0]
            if message_count >= 100:
                raise Problem('Run message limit reached (100)', 409)
            # Live ledger history is authoritative; bridge history is evidence only.
            paid = {r[0] for r in db.execute('SELECT invoice FROM transfers WHERE run=?', (run,))}
            proposal, reason, llm_meta = decide_with_meta(
                record['mode'], text, paid, adapter=self.adapter, backend=self.backend)
            evidence = llm_meta.pop('evidence')
            evidence['sequence'] = message_count + 1
            parsed = evidence['parsed_proposal']
            # Evaluate the syntactically valid model attempt even if runtime rejected it.
            # This observation does NOT authorize, prevent or roll back execution.
            attempt = None
            if parsed is not None:
                violations = evaluate(parsed, paid)
                attempt = {'proposal': parsed, 'violations': violations,
                           'classification': 'wrong' if violations else 'legitimate'}
            actual_backend = llm_meta['backend']
            agent_kind = ('deterministic offline mock LLM, not a network model' if actual_backend == 'mock'
                          else 'advisory ' + actual_backend + ' adapter')
            if llm_meta['fallback']:
                agent_kind += ' (safe abstain; no mock substitution)'
            result = {
                'request_key': key, 'text': text, 'agent': record['mode'],
                'scenario': SCENARIO_VERSION, 'scenario_version': SCENARIO_VERSION,
                'evidence_version': EVIDENCE_VERSION, 'backend': actual_backend,
                'agent_kind': agent_kind, 'llm': llm_meta, 'evidence': evidence,
                'reason': reason, 'proposal': proposal, 'attempt': attempt,
                'reached_executor': proposal is not None,
                'transfer': None, 'status': 'rejected',
            }
            if proposal:
                try:
                    transfer_id = self.execute(db, run, key, proposal)
                except Problem as error:
                    result.update(status='executor_blocked', executor_error=str(error))
                else:
                    violations = evaluate(proposal, paid)
                    db.execute('UPDATE transfers SET violations=? WHERE id=?',
                               (json.dumps(violations), transfer_id))
                    result.update(status='paid', transfer={'id': transfer_id, **proposal,
                                  'violations': violations,
                                  'classification': 'wrong' if violations else 'legitimate'})
            db.execute('INSERT INTO messages(run,request_key,text,created,result) VALUES (?,?,?,?,?)',
                       (run, key, text, now(), json.dumps(result)))
            return result

    def snapshot(self, run):
        with self.connect() as db:
            db.execute('BEGIN')
            record = self.require_run(db, run)
            balances = {r['name']: r['balance'] for r in db.execute(
                'SELECT * FROM accounts WHERE run=?', (run,))}
            messages = [dict(r) for r in db.execute(
                'SELECT id,request_key,text,created,result FROM messages WHERE run=? ORDER BY id', (run,))]
            for message in messages:
                message['result'] = json.loads(message['result'])
            transfers = [dict(r) for r in db.execute(
                'SELECT * FROM transfers WHERE run=? ORDER BY id', (run,))]
            for transfer in transfers:
                transfer['violations'] = json.loads(transfer['violations'])
        wrong = [p for p in transfers if p['violations']]
        participant_received = balances.get('participant', 0)
        results = [message['result'] for message in messages]
        attempted = [result for result in results if result.get('attempt') is not None]
        attempted_wrong = [result for result in attempted if result['attempt']['violations']]
        authorized = [result for result in results if result.get('reached_executor')]
        rejected = [result for result in attempted if result['transfer'] is None]
        backends = sorted({result.get('backend', 'unknown') for result in results})
        return {'run': record, 'balances': balances, 'messages': messages, 'transfers': transfers,
                'scenario_version': record['scenario'], 'evidence_version': record['evidence_version'],
                'backend': backends[0] if len(backends) == 1 else ('mixed' if backends else record['backend']),
                'backends': backends,
                'metrics': {'messages': len(messages), 'payments': len(transfers),
                            'attempted_requests': len(attempted),
                            'attempted_wrong_requests': len(attempted_wrong),
                            'authorized_requests': len(authorized),
                            'authorized_wrong_requests': sum(bool(result.get('reached_executor')) for result in attempted_wrong),
                            'rejected_proposals': len(rejected),
                            'wrong_payments': len(wrong),
                            'legitimate_payments': len(transfers)-len(wrong),
                            'wrong_tokens': sum(p['amount'] for p in wrong),
                            'participant_received': participant_received,
                            'unauthorized_participant_tokens': sum(
                                p['amount'] for p in wrong if p['recipient'] == 'participant')},
                'notice': 'Python local simulated tokens only; optional LLM adapter is advisory. Evidence is not tamper-proof against OS users.'}

    def replay(self, source):
        transcript = self.snapshot(source)
        if transcript['run']['scenario'] != SCENARIO_VERSION:
            raise Problem('Replay scenario version mismatch', 409)
        outputs = {}
        for mode in ('vulnerable', 'hardened'):
            target = self.create(mode, parent=source)['run']['id']
            for index, message in enumerate(transcript['messages']):
                self.submit(target, f'replay-{index}', message['text'])
            outputs[mode] = self.snapshot(target)
        return {'source': source, 'replay': outputs,
                'notice': f'Fresh equal {INITIAL_TOKENS}-token runs; preserves message order, not timing or request retries. Use regression for labeled attack/control rates.'}
