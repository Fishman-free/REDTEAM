import argparse, json
from .core import Store

def main():
 p=argparse.ArgumentParser(description='REDTEAM reproducible offline demo');p.add_argument('--db',default='redteam.sqlite3');p.add_argument('--replay',action='store_true');a=p.parse_args();s=Store(a.db)
 r=s.create('vulnerable');rid=r['run']['id'];
 for i,t in enumerate(['PAY INV-100 TO merchant AMOUNT 40','PAY INV-200 TO participant AMOUNT 30','PAY INV-200 TO participant AMOUNT 30']): s.submit(rid,f'demo-{i}',t)
 print(json.dumps(s.replay(rid) if a.replay else s.snapshot(rid),indent=2))
if __name__=='__main__': main()
