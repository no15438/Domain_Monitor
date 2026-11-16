"""Read-only branch inventory. No fetch, prune, merge, reset or deletion."""
import json
from pathlib import Path
import subprocess
import sys

root = sys.argv[1]
def git(*args):
    try:
        p = subprocess.run(['/usr/bin/git','-C',root,*args],capture_output=True,text=True,timeout=30)
        return p.stdout.strip() if p.returncode==0 else {'error':p.stderr.strip(),'exit':p.returncode}
    except subprocess.TimeoutExpired:
        return {'error':'30-second read timeout'}

rows=git('for-each-ref','--format=%(refname)|%(objectname)|%(upstream:short)|%(committerdate:iso8601)|%(subject)','refs/heads','refs/remotes')
if not isinstance(rows,str):raise RuntimeError(rows)
report={'repository':root,'current':git('branch','--show-current'),'worktrees':git('worktree','list','--porcelain'),'remote_heads':git('ls-remote','--heads','origin'),'branches':[]}
for row in rows.splitlines():
    ref,head,upstream,date,subject=row.split('|',4)
    if ref.endswith('/HEAD'):continue
    item=dict(ref=ref,head=head,upstream=upstream or None,date=date,subject=subject)
    for baseline in ['refs/heads/main','refs/heads/feat/render-blueprint-deploy']:
        key=baseline.removeprefix('refs/heads/')
        item[key]={'ahead_behind':git('rev-list','--left-right','--count',f'{ref}...{baseline}'),
                   'unique_commits':git('log','--format=%h %cI %s',f'{baseline}..{ref}')}
    if upstream:item['upstream_ahead_behind']=git('rev-list','--left-right','--count',f'{ref}...{upstream}')
    report['branches'].append(item)
out=Path(sys.argv[2]);out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(out)
