"""Fail-closed reception report inspection and lossless fragment append."""
from html.parser import HTMLParser
import re


class _ContentProbe(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.visible = False
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head"):
            self.hidden += 1
        elif tag in ("img", "svg", "object", "table"):
            self.visible = True

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head"):
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden and data.strip().strip("\u200b\u200e\u200f\ufeff"):
            self.visible = True


def existing_report_html(response):
    """Accept documented record/envelope forms; malformed data is not empty."""
    if not isinstance(response, dict) or response.get("success") is False:
        raise ValueError("Unable to inspect the existing report")
    record = response.get("data", response)
    if isinstance(record, list) and len(record) == 1:
        record = record[0]
    if not isinstance(record, dict) or not record:
        raise ValueError("Invalid reception record")
    if not any(key in record for key in (
        "report", "imagingWorkflow", "report_content", "receptionId", "ReceptionID",
        "patientId", "patient_id", "_id", "id",
    )):
        raise ValueError("Unrecognized reception record")
    workflow = record.get("imagingWorkflow") or {}
    if not isinstance(workflow, dict):
        raise ValueError("Invalid reception workflow")
    report = record.get("report") or workflow.get("report") or {}
    if not isinstance(report, dict):
        raise ValueError("Invalid reception report")
    for content in [report.get(k) for k in ("content", "findings", "html", "html_content")] + [record.get("report_content")]:
        if content is None:
            continue
        if not isinstance(content, str):
            raise ValueError("Unsupported report content")
        probe = _ContentProbe()
        probe.feed(content)
        if probe.visible:
            return content
    return ""


def append_report_html(previous, incoming):
    """Keep inline markup and order, avoiding nested full HTML documents."""
    def fragment(value):
        body = re.search(r"<body\b([^>]*)>([\s\S]*?)</body\s*>", value, re.I)
        return f"<div{body[1]}>{body[2]}</div>" if body else value
    return fragment(previous) + '\n<hr />\n' + fragment(incoming)
