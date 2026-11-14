"""Execution budgets and permission presets, not personas or extra system messages."""
PROFILES={
 'light':{'label':'Ligero','result_chars':4000,'history':'unchanged','rounds':50},
 'balanced':{'label':'Equilibrado','result_chars':8000,'history':'unchanged','rounds':50},
 'advanced':{'label':'Completo','result_chars':12000,'history':'unchanged','rounds':50},
}
LIGHT_TOOLS={
 'web_search','web_visit','fs_list','fs_read','doc_read','fs_write','fs_edit','fs_copy','fs_search','fs_manage',
 'web_render','draft_resume','file_history','code_check','project_map','sys_info','console','shell_run',
}
ALL_TOOLS={
 'web_search','web_visit','fs_list','fs_read','doc_read','fs_write','fs_edit','fs_copy','fs_search','fs_manage',
 'web_render','draft_resume','file_history','code_check','project_map','browser',
 'http_request','download','job_wait','job_status','job_list','job_stop','start','status','run','stop','screen_capture','ocr_image','window_list','window_focus','mouse_move','mouse_click','mouse_scroll','keyboard_type','keyboard_key','open','navigate','snapshot','text','click','fill','press','evaluate','wait','screenshot','cookies','network','browser_console','browser_download','tabs','close',
 'sys_info','hf_account','hf_cli','hf_transfer',
}
def normalize(value):return value if value in PROFILES else 'balanced'
def filter_enabled(enabled,profile,full_access):
    mode=normalize(profile)
    if mode=='light':return {name for name in enabled if name in LIGHT_TOOLS and (name!='console' or full_access)}
    if mode=='advanced':
        result=set(enabled)
        # A profile permits capabilities, but never enables an MCP by itself.
        if full_access and 'shell_run' in enabled:result.update({'job_wait','job_status','job_list','job_stop'})
        if not full_access:result.difference_update({'console','job_wait','job_status','job_list','job_stop','start','status','run','stop','screen_capture','ocr_image','window_list','window_focus','mouse_move','mouse_click','mouse_scroll','keyboard_type','keyboard_key'})
        return result
    return set(enabled)
def external_allowed(profile,full_access):
    return bool(full_access) and normalize(profile)!='light'
def tools_for_profile(tools,profile):
    # Profiles never override user-selected MCPs, remove callable parameters, or truncate instructions.
    return tools

def distinct_tools(tools):
    """Hide exact aliases from discovery; existing routes/history remain intact."""
    names={item['function']['name'] for item in tools}
    redundant={'autobrowser__navigate'} if 'autobrowser__open' in names else set()
    return [item for item in tools if item['function']['name'] not in redundant]
