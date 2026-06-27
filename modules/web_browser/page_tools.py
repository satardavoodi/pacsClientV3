"""Pure JavaScript builders for the Secretary/agent browser page tools.

NO Qt imports — every function returns a JavaScript SOURCE STRING that, when
run in the page via ``QWebEnginePage.runJavaScript``, evaluates to a
JSON-serializable value (str / bool / list / dict). User-supplied selectors
and values are **JSON-encoded** into the script (never string-concatenated),
so a hostile selector/value cannot break out of the JS literal. Every snippet
is wrapped in try/catch and returns a safe default, so a script error can
never raise into the page.

Keeping these here (pure, stdlib-only) makes them headless-unit-testable and
keeps ``widget.py`` focused on Qt wiring.
"""
from __future__ import annotations

import json
from typing import Optional


def _js(value) -> str:
    """JSON-encode a Python value into a safe JS literal."""
    return json.dumps("" if value is None else value)


# ── whole-page reads (no arguments) ──────────────────────────────────────
JS_PAGE_TEXT = (
    "(function(){try{return (document.body&&document.body.innerText)||'';}"
    "catch(e){return '';}})()"
)

JS_PAGE_HTML = (
    "(function(){try{return document.documentElement?"
    "document.documentElement.outerHTML:'';}catch(e){return '';}})()"
)

JS_SELECTED_TEXT = (
    "(function(){try{return (window.getSelection&&"
    "window.getSelection().toString())||'';}catch(e){return '';}})()"
)

# Structured "inspect the page" summary: title/url, element counts, visible
# headings, and the interactive inputs/buttons (so the agent can see forms and
# fields without scraping raw HTML).
JS_DOM_SUMMARY = r"""
(function(){
  try{
    function txt(el){return ((el&&el.innerText)||'').trim().slice(0,120);}
    var inputs=[];
    var nodes=document.querySelectorAll('input,select,textarea');
    for(var i=0;i<nodes.length && i<80;i++){
      var n=nodes[i];
      if((n.type||'')==='hidden') continue;
      inputs.push({tag:n.tagName.toLowerCase(),type:(n.type||''),
        name:(n.name||''),id:(n.id||''),placeholder:(n.placeholder||''),
        value_present:!!n.value});
    }
    var buttons=[];
    var bnodes=document.querySelectorAll(
      'button,input[type=submit],input[type=button],a[role=button]');
    for(var j=0;j<bnodes.length && j<50;j++){
      buttons.push({text:txt(bnodes[j]),id:(bnodes[j].id||''),
        name:(bnodes[j].name||'')});
    }
    var headings=[];
    var hnodes=document.querySelectorAll('h1,h2,h3');
    for(var k=0;k<hnodes.length && k<40;k++){headings.push(txt(hnodes[k]));}
    return {
      url:location.href, title:document.title||'',
      counts:{
        forms:document.forms.length,
        inputs:document.querySelectorAll('input,select,textarea').length,
        links:document.links.length,
        images:document.images.length,
        buttons:document.querySelectorAll(
          'button,input[type=submit],input[type=button]').length
      },
      headings:headings, inputs:inputs, buttons:buttons
    };
  }catch(e){return {error:String(e)};}
})()
"""


# ── element-scoped reads / actions (selector argument) ───────────────────
def js_find_element(selector: str) -> str:
    return (
        "(function(){try{var el=document.querySelector(%s);"
        "if(!el){return {found:false};}"
        "return {found:true,tag:el.tagName.toLowerCase(),id:(el.id||''),"
        "name:(el.name||''),type:(el.type||''),"
        "text:((el.innerText||el.value||'')+'').slice(0,300),"
        "href:(el.href||''),"
        "visible:!!(el.offsetWidth||el.offsetHeight||"
        "el.getClientRects().length)};"
        "}catch(e){return {found:false,error:String(e)};}})()" % _js(selector)
    )


def js_fill_field(selector: str, value: str) -> str:
    return (
        "(function(){try{var el=document.querySelector(%s);"
        "if(!el){return {ok:false,reason:'not_found'};}"
        "el.focus();el.value=%s;"
        "el.dispatchEvent(new Event('input',{bubbles:true}));"
        "el.dispatchEvent(new Event('change',{bubbles:true}));"
        "return {ok:true};}catch(e){return {ok:false,reason:String(e)};}})()"
        % (_js(selector), _js(value))
    )


def js_click(selector: str) -> str:
    return (
        "(function(){try{var el=document.querySelector(%s);"
        "if(!el){return {ok:false,reason:'not_found'};}"
        "el.click();return {ok:true};}"
        "catch(e){return {ok:false,reason:String(e)};}})()" % _js(selector)
    )


def js_submit_form(selector: Optional[str] = None) -> str:
    if selector:
        return (
            "(function(){try{var f=document.querySelector(%s);"
            "if(!f){return {ok:false,reason:'not_found'};}"
            "if(f.tagName!=='FORM'){f=f.form||f.closest('form');}"
            "if(!f){return {ok:false,reason:'no_form'};}"
            "if(f.requestSubmit){f.requestSubmit();}else{f.submit();}"
            "return {ok:true};}"
            "catch(e){return {ok:false,reason:String(e)};}})()" % _js(selector)
        )
    return (
        "(function(){try{var pw=document.querySelector('input[type=password]');"
        "var f=pw?(pw.form||pw.closest('form')):document.forms[0];"
        "if(!f){return {ok:false,reason:'no_form'};}"
        "if(f.requestSubmit){f.requestSubmit();}else{f.submit();}"
        "return {ok:true};}catch(e){return {ok:false,reason:String(e)};}})()"
    )


def js_extract_table(selector: Optional[str] = None,
                     max_rows: int = 100, max_cols: int = 40) -> str:
    sel = _js(selector) if selector else "null"
    return (
        "(function(){try{var sel=%s;"
        "var t=sel?document.querySelector(sel):document.querySelector('table');"
        "if(!t){return {found:false};}var rows=[];"
        "var trs=t.querySelectorAll('tr');"
        "for(var i=0;i<trs.length && i<%d;i++){"
        "var cells=trs[i].querySelectorAll('th,td');var row=[];"
        "for(var j=0;j<cells.length && j<%d;j++){"
        "row.push((cells[j].innerText||'').trim());}rows.push(row);}"
        "return {found:true,rows:rows};}"
        "catch(e){return {found:false,error:String(e)};}})()"
        % (sel, int(max_rows), int(max_cols))
    )


def js_get_links(max_links: int = 200) -> str:
    return (
        "(function(){try{var out=[];var a=document.links;"
        "for(var i=0;i<a.length && i<%d;i++){"
        "out.push({text:((a[i].innerText||'').trim()).slice(0,160),"
        "href:a[i].href||''});}return out;}catch(e){return [];}})()"
        % int(max_links)
    )


__all__ = [
    "JS_PAGE_TEXT", "JS_PAGE_HTML", "JS_SELECTED_TEXT", "JS_DOM_SUMMARY",
    "js_find_element", "js_fill_field", "js_click", "js_submit_form",
    "js_extract_table", "js_get_links",
]
