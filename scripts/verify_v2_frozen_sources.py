"""Compare bundled Python bytecode with current sources without executing it."""
import json
from pathlib import Path
import types
from PyInstaller.archive.readers import ZlibArchiveReader
from PyInstaller.loader.pyimod01_archive import PYZ_ITEM_NSPKG

root = Path(__file__).resolve().parents[1]
output = root/'reports/v2/conclusao'
archive = ZlibArchiveReader(str(output/'build/VRNorteStudio/PYZ-00.pyz'))
def shape(code):
    if not isinstance(code, types.CodeType):
        return code
    return (code.co_code, code.co_names, code.co_varnames, code.co_freevars, code.co_cellvars,
            code.co_argcount, code.co_kwonlyargcount, code.co_posonlyargcount, code.co_flags,
            tuple(shape(value) for value in code.co_consts))
checked, namespaces, mismatches = [], [], []
for name in sorted(archive.toc):
    if not name.startswith('vrsoft_extractor'):
        continue
    if archive.toc[name][0] == PYZ_ITEM_NSPKG and root.joinpath(*name.split('.')).is_dir():
        namespaces.append(name)
        continue
    path = root.joinpath(*name.split('.')).with_suffix('.py')
    if not path.is_file():
        path = root.joinpath(*name.split('.'))/'__init__.py'
    if not path.is_file():
        mismatches.append({'module':name,'reason':'source missing'})
        continue
    compiled = compile(path.read_bytes(), str(path), 'exec', optimize=1)
    frozen = archive.extract(name)
    checked.append(name)
    if shape(compiled) != shape(frozen):
        mismatches.append({'module':name,'reason':'bytecode differs'})
result = {'modules':len(checked),'namespace_packages':namespaces,'matched':not mismatches,'mismatches':mismatches,
          'semantic_modules_present':{name:name in archive.toc for name in ('numpy','onnxruntime','tokenizers')}}
(output/'frozen-source-check.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(result)
assert not mismatches
