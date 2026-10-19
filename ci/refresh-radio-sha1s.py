#!/usr/bin/env python3
"""Update proprietary onyx Android.mk to hash the EXACT radio files staged for this build."""
import hashlib, re, sys
from pathlib import Path
vendor = Path(sys.argv[1]); mk = vendor/'Android.mk'
pat = re.compile(r'(\$\(call add-radio-file-sha1-checked,radio/([^,]+),)([0-9a-f]{40})(\))')
replaced=0
lines=[]
for line in mk.read_text().splitlines(keepends=True):
 def sub(m):
  global replaced
  filename = vendor/'radio'/m.group(2)
  if not filename.is_file():raise FileNotFoundError(filename)
  h=hashlib.sha1()
  with filename.open('rb') as f:
   while data:=f.read(1024*1024):h.update(data)
  replaced+=1
  return m.group(1)+h.hexdigest()+m.group(4)
 lines.append(pat.sub(sub,line))
if replaced<20:raise RuntimeError(f'Unexpected Android.mk radio list: only {replaced} SHA1 entries')
mk.write_text(''.join(lines))
print(f'Updated {replaced} radio SHA1 digests from staged firmware: {mk}')
