"""Negotiated MCP tool contracts; no live Gateway or patient data."""
from modules.agent_gateway.mcp_bridge import McpBridge


def test_tool_has_output_schema_and_structured_result():
    bridge=McpBridge(list_actions=lambda:['get_visible_app_errors'],
        execute=lambda *a,**k:{'ok':True,'action':'get_visible_app_errors','data':{'visible_errors':[]}})
    listing=bridge.handle({'jsonrpc':'2.0','id':1,'method':'tools/list'})['result']
    assert listing['tools'][0]['outputSchema']['type']=='object'
    result=bridge.handle({'jsonrpc':'2.0','id':2,'method':'tools/call',
        'params':{'name':'get_visible_app_errors','arguments':{}}})['result']
    assert result['structuredContent']['ok'] is True
    assert result['isError'] is False


def test_unknown_tool_is_protocol_error_without_execution():
    calls=[]
    bridge=McpBridge(list_actions=lambda:[],execute=lambda *a,**k:calls.append(a))
    result=bridge.handle({'jsonrpc':'2.0','id':1,'method':'tools/call',
        'params':{'name':'unknown_tool','arguments':{}}})
    assert result['error']['code']==-32602
    assert calls==[]


def test_tool_failure_is_error_result_with_structured_feedback():
    bridge=McpBridge(list_actions=lambda:['get_visible_app_errors'],
        execute=lambda *a,**k:{'ok':False,'action':'get_visible_app_errors','error_code':'UNAVAILABLE'})
    result=bridge.handle({'jsonrpc':'2.0','id':1,'method':'tools/call',
        'params':{'name':'get_visible_app_errors','arguments':{}}})['result']
    assert result['isError'] is True
    assert result['structuredContent']['error_code']=='UNAVAILABLE'
