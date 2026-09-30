"""Workstation endpoint defaults; administrator environment overrides for cloud hosts."""
import os

AI_BASE = os.getenv("ECHOMIND_AI_BASE", "http://80.210.31.214:8085").rstrip("/")
ASSIST_BASE = os.getenv("ECHOMIND_ASSIST_BASE", "http://81.16.117.196:8082").rstrip("/")
URL_CHAT = AI_BASE + "/chat"
URL_GEN_REPORT = AI_BASE + "/generate_report"
URL_GEN_TRANSCRIPT = AI_BASE + "/generate_transcript"
URL_GEN_ASSISTANT = ASSIST_BASE + "/generate_assistant"
URL_SEARCH = ASSIST_BASE + "/search"
GAPGPT_API_URL = os.getenv("ECHOMIND_GAPGPT_URL", "https://api.gapgpt.app/v1/chat/completions")
GAPGPT_DEFAULT_MODEL = "gpt-5.2"
GAPGPT_TIMEOUT = 180
REPORT_MODALITIES = ["CT", "MRI", "SONOGRAPHY", "OBSTETRIC ULTRASOUND", "RADIOLOGY", "MAMOGRAPHY"]
