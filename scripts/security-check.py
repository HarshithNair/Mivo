"""Check project sources for accidental credential literals without printing values."""
from pathlib import Path
import re,subprocess,sys
root=Path(__file__).resolve().parents[1]
files=subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard'],cwd=root,text=True).splitlines()
patterns=[r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',r'AIza[0-9A-Za-z_-]{35}',r'\bsk-[A-Za-z0-9]{20,}',r'(?:PRIVATE_KEY|API_KEY|SECRET)\s*=\s*[\"\x27]?[A-Za-z0-9_/-]{24,}']
failed=[]
for file in files:
 p=root/file
 if p.suffix.lower() in ['.png','.jpg','.webp','.lock'] or file.endswith('package-lock.json'):continue
 try:text=p.read_text()
 except (UnicodeDecodeError,IsADirectoryError):continue
 if any(re.search(pattern,text) for pattern in patterns):failed.append(file)
for name in ['.env','.secrets/testnet-wallet.key','.secrets/quote-signer.key']:
 if subprocess.run(['git','check-ignore','-q',name],cwd=root).returncode:failed.append('not ignored: '+name)
if failed:
 print('FAIL: possible secret or ignore issue in: '+', '.join(failed));sys.exit(1)
print('PASS: source credential scan and private-file ignore rules')
