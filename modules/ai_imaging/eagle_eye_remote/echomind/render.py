"""Render every report field as inert, printable HTML (including unknown sections)."""
import html
import json


def parsed(value):
    if not isinstance(value, str):
        return value
    text = value.replace("<|end|>", "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        return json.loads(text)
    except ValueError:
        return text


def fragment(value, depth=0):
    if depth > 20:
        return "<p>" + html.escape(str(value)) + "</p>"
    if isinstance(value, dict):
        return "".join(f'<section><h{min(depth+2,6)}>{html.escape(str(key))}</h{min(depth+2,6)}>{fragment(item,depth+1)}</section>' for key,item in value.items())
    if isinstance(value, list):
        return "<ul>" + "".join("<li>" + fragment(item,depth+1) + "</li>" for item in value) + "</ul>"
    return '<p dir="auto">' + html.escape(str(value) if value is not None else "") + "</p>"


def report_html(result):
    body = fragment(parsed(result["content"]))
    if result.get('workflow') == 'web_search':
        from .web_search import render_content
        body = render_content(result['content'])
    if result.get("translation"):
        body += '<hr><article lang="fa" dir="rtl">' + fragment(parsed(result["translation"]["content"])) + '</article>'
    return '''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>EchoMind report</title>
<style>body{font:16px/1.7 Arial,sans-serif;color:#18283b;background:#eef2f6;margin:0;padding:32px}main{max-width:850px;margin:auto;background:white;padding:40px;border-radius:12px}header{color:#376784;border-bottom:2px solid #dae5ed}h1{font-size:24px}h2{font-size:20px}h3,h4,h5,h6{font-size:17px}p{white-space:pre-wrap;overflow-wrap:anywhere}section{break-inside:avoid}footer{margin-top:32px;color:#687587;font-size:12px}@media print{body{padding:0;background:white}main{padding:0}section{break-inside:auto}}</style></head>
<body><main><header><h1>EchoMind</h1></header>''' + body + '<footer>AI-PACS · EchoMind</footer></main></body></html>'
