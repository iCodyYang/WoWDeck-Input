from pathlib import Path
import hashlib,json,zipfile
base=Path(__file__).resolve().parent;out=base/'release';out.mkdir(exist_ok=True)
version=json.loads((base/'package.json').read_text())['version'];folder='WoWDeck Input'
def package(path,files):
 with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
  for f in sorted(files):z.write(f,Path(folder)/f.relative_to(base))
 assert zipfile.ZipFile(path).testzip() is None
 return hashlib.sha256(path.read_bytes()).hexdigest()
runtime=[base/n for n in ['main.py','model.py','package.json','plugin.json','LICENSE','NOTICE.md','README.md','INSTALL.md','VALIDATION.md']]
runtime += [p for d in ['dist','py_modules'] for p in (base/d).rglob('*') if p.is_file() and '__pycache__' not in p.parts and not p.name.endswith('.map')]
source=runtime+[base/n for n in ['.gitignore','build_release.py','build_frontend.mjs','tsconfig.json','rollup.config.js']]+[p for d in ['src','tests'] for p in (base/d).rglob('*') if p.is_file() and '__pycache__' not in p.parts]
manifest={}
for suffix,files in [('',runtime),('-source',source)]:
 path=out/f'WoWDeck-Input-{version}{suffix}.zip';manifest[path.name]=package(path,files)
(out/'SHA256SUMS.json').write_text(json.dumps(manifest,indent=2)+'\n');print(json.dumps(manifest,indent=2))
