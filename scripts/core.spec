from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules, collect_data_files
root=Path(SPECPATH).parent
datas=[(str(root/'agent/index.html'),'agent'),(str(root/'agent/guide.html'),'agent'),(str(root/'agent/ui-mcp.js'),'agent'),(str(root/'agent/ui-motion.js'),'agent'),(str(root/'agent/ui-i18n.js'),'agent'),(str(root/'agent/ui-panels.css'),'agent'),(str(root/'agent/locales.json'),'agent'),(str(root/'agent/ocr.ps1'),'agent'),(str(root/'agent/scene_probe.js'),'agent'),(str(root/'agent/pick_model_file.py'),'agent'),
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
binaries=[];hidden=['components','app_updates','model_hub','external_models','hardware_stats','engine_recommendations','sandbox_exec','load_settings','memory_estimate','plugins','draft_models','verification_evidence','output_paths','local_console','extensions','agent_profiles','engine_updates','thinking_policy','tool_approvals','mcp_options','agent','desktop_runtime','engine_manager','runtime_paths','pc_mcp','hf_mcp','buscador_mcp','busqueda_local','http_tools_mcp','browser_mcp','admin_mcp','admin_helper','computer_mcp','gguf_reader','gguf_catalog','strata_tokenizer','tkinter','tkinter.filedialog']
datas+=collect_data_files('justext')
datas+=collect_data_files('mcp');hidden+=collect_submodules('mcp',filter=lambda name:not name.startswith('mcp.cli'))
for package in ('huggingface_hub','ddgs','trafilatura','websockets'):
    data,libs,modules=collect_all(package);datas+=data;binaries+=libs;hidden+=modules
hidden+=collect_submodules('serve',filter=lambda name:not name.split('.')[-1].startswith('test_'))
a=Analysis([str(root/'backend.py')],pathex=[str(root),str(root/'agent'),str(root/'tools'),str(root/'web_mcp')],
           binaries=binaries,datas=datas,hiddenimports=hidden,hookspath=[],runtime_hooks=[],excludes=['pytest','IPython','torch','tensorflow','matplotlib','PyQt5','PyQt6'])
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='strata-core',debug=False,bootloader_ignore_signals=False,strip=False,upx=False,console=True,icon=str(root/'desktop/src-tauri/icons/icon.ico'))
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='core')
