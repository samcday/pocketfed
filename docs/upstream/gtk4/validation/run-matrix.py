#!/usr/bin/python3
from pathlib import Path
import argparse,json,subprocess,sys
parser=argparse.ArgumentParser()
parser.add_argument('--harness',required=True)
parser.add_argument('--library-dir',required=True)
parser.add_argument('--dependency-dir',required=True)
parser.add_argument('--output',required=True)
parser.add_argument('--label',required=True)
parser.add_argument('--dbus-run-session',default='/usr/bin/dbus-run-session')
parser.add_argument('--dbus-daemon')
args=parser.parse_args()
harness=Path(args.harness).resolve(); output=Path(args.output).resolve()
output.mkdir(parents=True,exist_ok=True)
cases=[('hello',None,'hello',0),('unicode',None,'café',0),('punctuation',None,'hello!',0),('layout','layout','hello',0),('reset','reset','hello',1),('cursor','cursor','hello',1),('focus','focus','hello',0)]
results=[]
for name,action,word,expected in cases:
 case=output/(args.label+'-'+name)
 command=[args.dbus_run_session]+(['--dbus-daemon='+args.dbus_daemon] if args.dbus_daemon else [])+['--config-file='+str(harness/'dbus.conf'),'--','/usr/bin/python3',str(harness/'run-case.py'),'--library-dir',args.library_dir,'--dependency-dir',args.dependency_dir,'--output',str(case),'--word',word]
 if action: command+=['--action',action]
 trial=subprocess.run(command,capture_output=True,text=True)
 if not (case/'result.json').exists(): raise RuntimeError(trial.stderr+trial.stdout)
 result=json.loads((case/'result.json').read_text())
 result.update(case=name,expected_exit=expected,passed=trial.returncode==expected)
 results.append(result)
 print(args.label,name,'PASS' if result['passed'] else 'FAIL',result['classification'],result.get('error',''),flush=True)
(output/(args.label+'-summary.json')).write_text(json.dumps(results,indent=2)+'\n')
sys.exit(0 if all(r['passed'] for r in results) else 1)
