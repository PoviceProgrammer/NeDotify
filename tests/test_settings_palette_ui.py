"""A dormant editor palette must not replace the selected preset at startup."""
import json
from pathlib import Path
import shutil
import subprocess
import pytest

SOURCE=Path(__file__).resolve().parents[1]/'ui/web_new_v2/js/settings.js'

def test_legacy_colours_require_explicit_activation():
    node=shutil.which('node')
    if not node:
        pytest.skip('Node unavailable')
    script=f"""
    import vm from 'node:vm';import assert from 'node:assert/strict';
    const properties=new Map();
    const context=vm.createContext({{
      window:{{settings:{{theme:{{}}}},addEventListener:()=>{{}}}},localStorage:{{getItem:()=>null}},
      document:{{documentElement:{{style:{{setProperty:(k,v)=>properties.set(k,v),removeProperty:k=>properties.delete(k)}}}},getElementById:()=>null,addEventListener:()=>{{}}}},
      getComputedStyle:()=>({{getPropertyValue:()=>''}}),syncCustomColorFields:()=>{{}}
    }});
    vm.runInContext({json.dumps(SOURCE.read_text(encoding='utf-8'))}.replace(/^import .*;\\r?$/gm,'').replace(/\\bexport\\s+/g,'')+'\\nglobalThis.subject={{restoreCustomPalette}};',context);
    context.subject.restoreCustomPalette({{color_primary:'#ff0000',color_bg:'#00ff88',color_text:'#ff0000'}});
    assert.equal(properties.size,0,'Legacy editor colours must stay dormant');
    context.subject.restoreCustomPalette({{custom_palette_enabled:true,color_primary:'#118855',color_bg:'#102019',color_text:'#ffffff'}});
    assert.equal(properties.get('--bg-main'),'#102019');assert.equal(properties.get('--primary-rgb'),'17, 136, 85');
    context.subject.restoreCustomPalette({{custom_palette_enabled:false,color_primary:'#ff0000',color_bg:'#00ff88'}});
    assert.equal(properties.size,0,'Disabling the custom palette must remove its CSS overrides');
    """
    result=subprocess.run([node,'--input-type=module'],input=script,text=True,encoding='utf-8',capture_output=True,timeout=10)
    assert result.returncode==0,result.stderr
