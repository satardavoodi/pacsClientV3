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

JS_PAGE_TITLE = (
    "(function(){try{return document.title||'';}catch(e){return '';}})()"
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

JS_SCROLL_STATE = r"""
(function(){
  try{
    var d=document.documentElement||document.body;
    return {
      x: window.scrollX||0, y: window.scrollY||0,
      width: d ? d.scrollWidth : 0,
      height: d ? d.scrollHeight : 0,
      viewport_width: window.innerWidth||0,
      viewport_height: window.innerHeight||0
    };
  }catch(e){return {error:String(e)};}
})()
"""

JS_SELECTED_ELEMENT = r"""
(function(){
  try{
    var el=document.activeElement;
    if(!el){return {found:false};}
    function path(n){
      if(!n || !n.tagName){return '';}
      if(n.id){return '#'+n.id;}
      var parts=[];
      while(n && n.nodeType===1 && parts.length<8){
        var s=n.tagName.toLowerCase();
        if(n.id){s+='#'+n.id;parts.unshift(s);break;}
        if(n.className && typeof n.className==='string'){
          s+='.'+n.className.trim().split(/\s+/).slice(0,2).join('.');
        }
        var i=1, p=n;
        while((p=p.previousElementSibling)){ if(p.tagName===n.tagName){i++;} }
        s+=':nth-of-type('+i+')';
        parts.unshift(s); n=n.parentElement;
      }
      return parts.join(' > ');
    }
    var r=el.getBoundingClientRect ? el.getBoundingClientRect() : null;
    return {
      found:true, selector:path(el), tag:el.tagName.toLowerCase(),
      id:el.id||'', name:el.name||'', type:el.type||'',
      role:el.getAttribute('role')||'', aria_label:el.getAttribute('aria-label')||'',
      text:((el.innerText||el.value||'')+'').trim().slice(0,300),
      value_present:!!el.value,
      rect:r?{x:r.x,y:r.y,width:r.width,height:r.height}:null
    };
  }catch(e){return {found:false,error:String(e)};}
})()
"""

JS_NETWORK_ENTRIES = r"""
(function(){
  try{
    var out=[];
    var entries=(performance && performance.getEntriesByType) ?
      performance.getEntriesByType('resource') : [];
    for(var i=Math.max(0, entries.length-200); i<entries.length; i++){
      var e=entries[i];
      out.push({
        name:e.name||'', initiatorType:e.initiatorType||'',
        startTime:Math.round(e.startTime||0),
        duration:Math.round(e.duration||0),
        transferSize:e.transferSize||0,
        encodedBodySize:e.encodedBodySize||0,
        decodedBodySize:e.decodedBodySize||0
      });
    }
    var captured=[];
    try{
      captured = (window.__aipacsNetworkCapture &&
        window.__aipacsNetworkCapture.getResponses &&
        window.__aipacsNetworkCapture.getResponses()) || [];
    }catch(_e){captured=[];}
    return {supported:true, entries:out, count:out.length,
      captured_responses:captured, captured_count:captured.length,
      body_capture_supported:!!(window.__aipacsNetworkCapture),
      note:'Response bodies are captured for fetch/XMLHttpRequest calls made after the AI-PACS injection script installs. Bodies are capped and limited to text/JSON-like content.'};
  }catch(e){return {supported:false, entries:[], count:0, error:String(e)};}
})()
"""

JS_NETWORK_CAPTURE_INSTALL = r"""
(function(){
  try{
    if(window.__aipacsNetworkCapture && window.__aipacsNetworkCapture.installed){return;}
    var MAX_ITEMS=100, MAX_BODY=120000;
    var items=[];
    function nowIso(){try{return new Date().toISOString();}catch(_e){return '';}}
    function cleanHeaders(headers){
      var out={};
      try{
        if(!headers){return out;}
        if(headers.forEach){headers.forEach(function(v,k){out[k]=String(v).slice(0,500);});}
        else if(Array.isArray(headers)){headers.forEach(function(p){if(p&&p.length>=2){out[String(p[0])]=String(p[1]).slice(0,500);}});}
        else if(typeof headers==='object'){Object.keys(headers).forEach(function(k){out[k]=String(headers[k]).slice(0,500);});}
      }catch(_e){}
      return out;
    }
    function contentLooksText(ct){
      ct=(ct||'').toLowerCase();
      return !ct || ct.indexOf('json')>=0 || ct.indexOf('text/')>=0 ||
        ct.indexOf('xml')>=0 || ct.indexOf('html')>=0 ||
        ct.indexOf('javascript')>=0 || ct.indexOf('form-urlencoded')>=0;
    }
    function push(item){
      try{
        item.captured_at=nowIso();
        if(item.body && item.body.length>MAX_BODY){
          item.body_truncated=true;
          item.body=item.body.slice(0,MAX_BODY);
        }
        items.push(item);
        if(items.length>MAX_ITEMS){items=items.slice(items.length-MAX_ITEMS);}
      }catch(_e){}
    }
    window.__aipacsNetworkCapture={
      installed:true,
      getResponses:function(){return items.slice();},
      clear:function(){items=[];return true;},
      limits:{max_items:MAX_ITEMS,max_body_chars:MAX_BODY}
    };

    var origFetch=window.fetch;
    if(origFetch && !origFetch.__aipacsWrapped){
      var wrappedFetch=function(input, init){
        var started=Date.now();
        var method='GET', url='';
        try{
          if(typeof input==='string'){url=input;}
          else if(input && input.url){url=input.url;}
          method=((init&&init.method)||(input&&input.method)||'GET')+'';
        }catch(_e){}
        return origFetch.apply(this, arguments).then(function(resp){
          try{
            var clone=resp.clone();
            var ct=(clone.headers&&clone.headers.get&&clone.headers.get('content-type'))||'';
            var base={
              source:'fetch', url:url || clone.url || '', method:method.toUpperCase(),
              status:resp.status, ok:!!resp.ok, status_text:resp.statusText||'',
              response_url:resp.url||'', content_type:ct,
              headers:cleanHeaders(resp.headers), duration_ms:Date.now()-started
            };
            if(contentLooksText(ct)){
              clone.text().then(function(txt){base.body=txt||'';push(base);})
                .catch(function(err){base.body_error=String(err);push(base);});
            }else{
              base.body_omitted='non_text_content_type';push(base);
            }
          }catch(err){push({source:'fetch',url:url,method:method,error:String(err),duration_ms:Date.now()-started});}
          return resp;
        }, function(err){
          push({source:'fetch',url:url,method:method,error:String(err),duration_ms:Date.now()-started});
          throw err;
        });
      };
      wrappedFetch.__aipacsWrapped=true;
      window.fetch=wrappedFetch;
    }

    var XHR=window.XMLHttpRequest;
    if(XHR && XHR.prototype && !XHR.prototype.__aipacsWrapped){
      var origOpen=XHR.prototype.open;
      var origSend=XHR.prototype.send;
      XHR.prototype.open=function(method,url){
        try{this.__aipacsCapture={method:String(method||'GET').toUpperCase(),url:String(url||''),started:0};}catch(_e){}
        return origOpen.apply(this, arguments);
      };
      XHR.prototype.send=function(body){
        try{
          var cap=this.__aipacsCapture||{method:'GET',url:''};
          cap.started=Date.now();
          this.__aipacsCapture=cap;
          this.addEventListener('loadend', function(){
            try{
              var ct='';
              try{ct=this.getResponseHeader('content-type')||'';}catch(_e){}
              var item={
                source:'xhr', url:cap.url||'', method:cap.method||'GET',
                status:this.status, ok:(this.status>=200&&this.status<400),
                status_text:this.statusText||'', response_url:this.responseURL||'',
                content_type:ct, duration_ms:Date.now()-(cap.started||Date.now())
              };
              if(contentLooksText(ct) && (this.responseType==='' || this.responseType==='text')){
                try{item.body=this.responseText||'';}catch(err){item.body_error=String(err);}
              }else{
                item.body_omitted=this.responseType?('response_type_'+this.responseType):'non_text_content_type';
              }
              push(item);
            }catch(err){push({source:'xhr',url:(cap&&cap.url)||'',error:String(err)});}
          });
        }catch(_e){}
        return origSend.apply(this, arguments);
      };
      XHR.prototype.__aipacsWrapped=true;
    }
  }catch(e){
    try{window.__aipacsNetworkCapture={installed:false,error:String(e),getResponses:function(){return [];},clear:function(){return false;}};}catch(_e){}
  }
})()
"""

JS_CLEAR_NETWORK_CAPTURE = r"""
(function(){
  try{
    if(window.__aipacsNetworkCapture && window.__aipacsNetworkCapture.clear){
      return {ok:!!window.__aipacsNetworkCapture.clear()};
    }
    return {ok:false, reason:'capture_not_installed'};
  }catch(e){return {ok:false, reason:String(e)};}
})()
"""

JS_STRUCTURED_PAGE_DATA = r"""
(function(){
  try{
    function clean(s,n){return ((s||'')+'').replace(/\s+/g,' ').trim().slice(0,n||400);}
    function attrs(el,names){var o={}; for(var i=0;i<names.length;i++){var v=el.getAttribute(names[i]); if(v){o[names[i]]=v;}} return o;}
    var meta=[];
    var m=document.querySelectorAll('meta');
    for(var i=0;i<m.length && i<80;i++){
      var k=m[i].getAttribute('name')||m[i].getAttribute('property')||m[i].getAttribute('http-equiv')||'';
      var v=m[i].getAttribute('content')||'';
      if(k||v){meta.push({name:k, content:clean(v,500)});}
    }
    var jsonld=[];
    var scripts=document.querySelectorAll('script[type="application/ld+json"]');
    for(var j=0;j<scripts.length && j<20;j++){
      var raw=scripts[j].textContent||'';
      try{jsonld.push(JSON.parse(raw));}catch(_e){jsonld.push({raw:clean(raw,1000)});}
    }
    var forms=[];
    for(var f=0; f<document.forms.length && f<20; f++){
      var form=document.forms[f], fields=[];
      var nodes=form.querySelectorAll('input,select,textarea,button');
      for(var q=0;q<nodes.length && q<80;q++){
        var n=nodes[q];
        fields.push(Object.assign({
          tag:n.tagName.toLowerCase(), type:n.type||'', name:n.name||'', id:n.id||'',
          placeholder:n.placeholder||'', text:clean(n.innerText||n.value,120),
          value_present:!!n.value
        }, attrs(n,['aria-label','role','autocomplete'])));
      }
      forms.push({id:form.id||'', name:form.name||'', action:form.action||'', method:form.method||'', fields:fields});
    }
    var tables=[];
    var ts=document.querySelectorAll('table');
    for(var t=0;t<ts.length && t<20;t++){
      var rows=[], trs=ts[t].querySelectorAll('tr');
      for(var r=0;r<trs.length && r<30;r++){
        var cells=trs[r].querySelectorAll('th,td'), row=[];
        for(var c=0;c<cells.length && c<20;c++){row.push(clean(cells[c].innerText,200));}
        rows.push(row);
      }
      tables.push({index:t, id:ts[t].id||'', className:ts[t].className||'', rows:rows});
    }
    var cards=[];
    var cardNodes=document.querySelectorAll('[role=article],article,.card,.panel,.tile,[data-card]');
    for(var a=0;a<cardNodes.length && a<50;a++){
      cards.push({tag:cardNodes[a].tagName.toLowerCase(), id:cardNodes[a].id||'',
        className:cardNodes[a].className||'', text:clean(cardNodes[a].innerText,700)});
    }
    return {
      url:location.href, title:document.title||'', meta:meta, json_ld:jsonld,
      forms:forms, tables:tables, cards:cards,
      scroll:{x:window.scrollX||0,y:window.scrollY||0,
        viewport_width:window.innerWidth||0, viewport_height:window.innerHeight||0}
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


def js_dom_snapshot(max_elements: int = 300) -> str:
    return (
        "(function(){try{function clean(s,n){return ((s||'')+'').replace(/\\s+/g,' ').trim().slice(0,n||180);}"
        "function css(el){if(!el||!el.tagName)return '';if(el.id)return '#'+el.id;"
        "var s=el.tagName.toLowerCase();if(el.className&&typeof el.className==='string'){"
        "s+='.'+el.className.trim().split(/\\s+/).slice(0,2).join('.');}return s;}"
        "var nodes=document.body?document.body.querySelectorAll('body *'):[];var out=[];"
        "for(var i=0;i<nodes.length&&out.length<%d;i++){var el=nodes[i];"
        "var rect=el.getBoundingClientRect?el.getBoundingClientRect():null;"
        "var visible=!!(el.offsetWidth||el.offsetHeight||el.getClientRects().length);"
        "var interactive=el.matches&&el.matches('a,button,input,select,textarea,[role=button],[onclick]');"
        "var text=clean(el.innerText||el.value||'',220);"
        "if(!visible&&!interactive&&!text)continue;"
        "out.push({tag:el.tagName.toLowerCase(),selector:css(el),id:el.id||'',"
        "className:(typeof el.className==='string'?el.className:''),role:el.getAttribute('role')||'',"
        "aria_label:el.getAttribute('aria-label')||'',name:el.name||'',type:el.type||'',"
        "text:text,visible:visible,interactive:!!interactive,"
        "rect:rect?{x:Math.round(rect.x),y:Math.round(rect.y),width:Math.round(rect.width),height:Math.round(rect.height)}:null});}"
        "return {url:location.href,title:document.title||'',count:out.length,elements:out};}"
        "catch(e){return {error:String(e),elements:[]};}})()" % int(max_elements)
    )


def js_accessibility_tree(max_nodes: int = 250) -> str:
    return (
        "(function(){try{function clean(s,n){return ((s||'')+'').replace(/\\s+/g,' ').trim().slice(0,n||180);}"
        "function roleOf(el){return el.getAttribute('role')||({A:'link',BUTTON:'button',INPUT:'input',SELECT:'combobox',TEXTAREA:'textbox',FORM:'form',TABLE:'table',IMG:'img'}[el.tagName]||'');}"
        "function nameOf(el){return clean(el.getAttribute('aria-label')||el.getAttribute('alt')||el.innerText||el.value||el.title||'',220);}"
        "var sel='a,button,input,select,textarea,form,table,img,[role],[aria-label],h1,h2,h3,h4,h5,h6';"
        "var nodes=document.querySelectorAll(sel), out=[];"
        "for(var i=0;i<nodes.length&&out.length<%d;i++){var el=nodes[i];"
        "var role=roleOf(el), name=nameOf(el);"
        "var visible=!!(el.offsetWidth||el.offsetHeight||el.getClientRects().length);"
        "if(!visible&&!name)continue;"
        "out.push({role:role,name:name,tag:el.tagName.toLowerCase(),id:el.id||'',"
        "type:el.type||'',checked:!!el.checked,disabled:!!el.disabled,visible:visible});}"
        "return {url:location.href,title:document.title||'',count:out.length,nodes:out,"
        "note:'Approximate accessibility tree derived from DOM roles/ARIA; Qt accessibility tree is not exposed here.'};}"
        "catch(e){return {error:String(e),nodes:[]};}})()" % int(max_nodes)
    )


def js_get_inputs(max_inputs: int = 200) -> str:
    return (
        "(function(){try{var out=[], nodes=document.querySelectorAll('input,select,textarea');"
        "for(var i=0;i<nodes.length&&i<%d;i++){var n=nodes[i];"
        "if((n.type||'')==='hidden')continue;"
        "out.push({tag:n.tagName.toLowerCase(),type:n.type||'',name:n.name||'',id:n.id||'',"
        "placeholder:n.placeholder||'',value:n.value||'',value_present:!!n.value,"
        "checked:!!n.checked,disabled:!!n.disabled,required:!!n.required,"
        "aria_label:n.getAttribute('aria-label')||'',autocomplete:n.getAttribute('autocomplete')||''});}"
        "return out;}catch(e){return [];}})()" % int(max_inputs)
    )


def js_get_buttons(max_buttons: int = 200) -> str:
    return (
        "(function(){try{function clean(s){return ((s||'')+'').replace(/\\s+/g,' ').trim().slice(0,180);}"
        "var out=[], nodes=document.querySelectorAll('button,input[type=submit],input[type=button],a[role=button],[role=button]');"
        "for(var i=0;i<nodes.length&&i<%d;i++){var n=nodes[i];"
        "out.push({tag:n.tagName.toLowerCase(),type:n.type||'',name:n.name||'',id:n.id||'',"
        "text:clean(n.innerText||n.value||n.getAttribute('aria-label')||''),disabled:!!n.disabled,"
        "aria_label:n.getAttribute('aria-label')||'',visible:!!(n.offsetWidth||n.offsetHeight||n.getClientRects().length)});}"
        "return out;}catch(e){return [];}})()" % int(max_buttons)
    )


def js_type_text(selector: Optional[str], text: str) -> str:
    sel = _js(selector) if selector else "null"
    return (
        "(function(){try{var sel=%s;var el=sel?document.querySelector(sel):document.activeElement;"
        "if(!el){return {ok:false,reason:'not_found'};}el.focus();"
        "var val=%s;if(typeof el.value==='string'){"
        "var st=el.selectionStart, en=el.selectionEnd;"
        "if(typeof st==='number'&&typeof en==='number'){el.value=el.value.slice(0,st)+val+el.value.slice(en);"
        "el.selectionStart=el.selectionEnd=st+val.length;}else{el.value+=val;}"
        "}else{document.execCommand&&document.execCommand('insertText',false,val);}"
        "el.dispatchEvent(new Event('input',{bubbles:true}));"
        "el.dispatchEvent(new Event('change',{bubbles:true}));return {ok:true};}"
        "catch(e){return {ok:false,reason:String(e)};}})()" % (sel, _js(text))
    )


def js_scroll_page(delta_x: int = 0, delta_y: int = 0,
                   x: Optional[int] = None, y: Optional[int] = None) -> str:
    if x is not None or y is not None:
        return (
            "(function(){try{window.scrollTo(%s,%s);return {ok:true,x:window.scrollX||0,y:window.scrollY||0};}"
            "catch(e){return {ok:false,reason:String(e)};}})()"
            % (int(x or 0), int(y or 0))
        )
    return (
        "(function(){try{window.scrollBy(%d,%d);return {ok:true,x:window.scrollX||0,y:window.scrollY||0};}"
        "catch(e){return {ok:false,reason:String(e)};}})()"
        % (int(delta_x), int(delta_y))
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
    "JS_PAGE_TEXT", "JS_PAGE_HTML", "JS_SELECTED_TEXT", "JS_PAGE_TITLE",
    "JS_DOM_SUMMARY", "JS_SCROLL_STATE", "JS_SELECTED_ELEMENT",
    "JS_NETWORK_ENTRIES", "JS_NETWORK_CAPTURE_INSTALL",
    "JS_CLEAR_NETWORK_CAPTURE", "JS_STRUCTURED_PAGE_DATA",
    "js_dom_snapshot", "js_accessibility_tree", "js_get_inputs",
    "js_get_buttons", "js_find_element", "js_type_text", "js_scroll_page",
    "js_fill_field", "js_click", "js_submit_form", "js_extract_table",
    "js_get_links",
]
