from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules, collect_data_files
root=Path(SPECPATH).parent
datas=[(str(root/'agent/ui/dist'),'agent/ui/dist'),(str(root/'agent/ocr.ps1'),'agent'),(str(root/'agent/scene_probe.js'),'agent'),(str(root/'agent/pick_model_file.py'),'agent'),
       (str(root/'serve/chat_template.jinja'),'serve'),(str(root/'browser'),'browser')]
# V_AGENT_RELEASE=1 (scripts/build-release.cmd): no engines, no seeds, empty model data from
# scripts/prepare_release.py. Otherwise the developer build bundles the local runtime and seeds.
import os
RELEASE=os.environ.get('V_AGENT_RELEASE')=='1'
data_root=root/'build/release-data' if RELEASE else root
datas+=[(str(data_root/'agent'/name),'agent') for name in ('model-profiles.json','creator-recommendations.json','template-provenance.json')]
datas+=[(str(data_root/'runtime'),'runtime')]
if not RELEASE:datas.append((str(root/'seeds'),'seeds'))
datas.append((str(root/'agent/assets/branding'),'agent/assets/branding'))
binaries=[];hidden=['nvml','render_check','verify','code_insight','agent_resilience','ask_user','shell_hygiene','components','app_updates','model_hub','external_models','model_mover','instructions','hardware_stats','engine_recommendations','sandbox_exec','load_settings','memory_estimate','plugins','draft_models','verification_evidence','output_paths','local_console','extensions','agent_profiles','engine_updates','thinking_policy','tool_approvals','mcp_options','doc_extractor','agent','desktop_runtime','engine_manager','maya_engine','runtime_paths','pc_mcp','hf_mcp','buscador_mcp','busqueda_local','http_tools_mcp','browser_mcp','admin_mcp','admin_helper','computer_mcp','gguf_reader','gguf_catalog','strata_tokenizer','tkinter','tkinter.filedialog']
datas+=collect_data_files('justext')
datas+=collect_data_files('mcp');hidden+=collect_submodules('mcp',filter=lambda name:not name.startswith('mcp.cli'))
for package in ('huggingface_hub','ddgs','trafilatura','websockets','pypdf','pdfplumber','pdfminer','pypdfium2','docx','openpyxl','pptx','et_xmlfile','xlsxwriter'):
    data,libs,modules=collect_all(package);datas+=data;binaries+=libs;hidden+=modules
hidden+=collect_submodules('pyflakes')  # code_check: static analysis of Python
hidden+=collect_submodules('serve',filter=lambda name:not name.split('.')[-1].startswith('test_'))
a=Analysis([str(root/'backend.py')],pathex=[str(root),str(root/'agent'),str(root/'tools'),str(root/'web_mcp')],
           binaries=binaries,datas=datas,hiddenimports=hidden,hookspath=[],runtime_hooks=[],excludes=['pytest','IPython','torch','tensorflow','matplotlib','PyQt5','PyQt6'])
# Installed layout (core\):
#   v-agent-core.exe          the core program
#   lib\                      its runtime (PyInstaller's contents folder, named "_internal" by default)
#     python313.dll, python3.dll, VCRUNTIME140*.dll, base_library.zip   what Python's start needs right there
#     python3.13\lib-dynload\  Python's compiled modules (.pyd) and the libraries they load (OpenSSL,
#                               SQLite, libffi, Tcl/Tk): the bootloader puts this folder on sys.path itself,
#                               and Windows finds each .pyd's libraries next to it
#     agent\, serve\, browser\, runtime\ …   V-Agent's own files;   <package>\, <package>.dist-info\
#                               the third-party packages and the metadata importlib.metadata reads
# Windows 10/11 already have the Universal C Runtime and wintrust.dll: their copies (api-ms-win-*.dll,
# ucrtbase.dll, wintrust.dll; over 40 loose files) are not shipped.
import sys as _sys
_DYNLOAD = 'python%d.%d/lib-dynload' % _sys.version_info[:2]
_WITH_EXTENSIONS = {'libssl-3.dll', 'libcrypto-3.dll', 'libffi-8.dll', 'sqlite3.dll', 'tcl86t.dll', 'tk86t.dll'}
_SYSTEM = {'ucrtbase.dll', 'wintrust.dll'}
_layout = []
for _dest, _src, _kind in a.binaries:
    _name = _dest.replace('\\', '/')
    _base = _name.rsplit('/', 1)[-1].lower()
    if '/' not in _name and (_base.startswith('api-ms-win-') or _base in _SYSTEM):
        continue
    if '/' not in _name and (_base.endswith('.pyd') or _base in _WITH_EXTENSIONS):
        _dest = _DYNLOAD + '/' + _name
    _layout.append((_dest, _src, _kind))
a.binaries = _layout
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='v-agent-core',contents_directory='lib',debug=False,bootloader_ignore_signals=False,strip=False,upx=False,console=True,icon=str(root/'desktop/src-tauri/icons/icon.ico'))
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='core')
