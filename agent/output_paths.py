"""Host-owned file destinations for network tools; model arguments cannot expand scope."""
from pathlib import Path
from urllib.parse import urlsplit

def prepare_output_paths(name,args,workspace,full_access):
    out=dict(args)
    if name not in ('web__download','web__http_request','autobrowser__browser_download'):return out
    if workspace is None:raise ValueError('File-producing network tools require a conversation workspace.')
    if out.get('allow_private') and not full_access:
        from access_policy import AccessDenied
        raise AccessDenied('Private network access requires Full access; this argument cannot expand permissions.')
    field='save_path' if name=='web__http_request' else 'path'
    if out.get(field):out[field]=str(workspace.path(out[field],full_access))
    elif field=='path':
        filename=Path(urlsplit(str(out.get('url',''))).path).name or 'download.bin'
        filename=''.join(c if c.isalnum() or c in '._-' else '_' for c in filename)[:160] or 'download.bin'
        out[field]=str(workspace.path('downloads/'+filename,False))
    if name=='web__http_request':out['download_dir']=str(workspace.path('downloads',False))
    return out
