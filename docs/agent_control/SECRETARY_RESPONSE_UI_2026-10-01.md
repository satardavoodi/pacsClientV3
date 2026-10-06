# Secretary response UI and local English speech

Source receipt, 2026-10-01. The existing 28-pixel stage summary remains, while replies now open a modeless 560x340 response panel with 16-pixel selectable text, Read aloud, Stop, optional Speak new replies, and Details. Details are bounded to 720x480 rather than filling the host. Existing confirmation and execution routes are retained.

Optional Qt QTextToSpeech uses installed Windows SAPI English voices. This is local speech synthesis, not company AI inference and not a cloud fallback. There is no new provider, credential or network route. Replies are spoken after completion, not streamed from the model. Voice quality and supported languages depend on installed voices. Automatic playback defaults off; English synthesis does not translate Persian replies. Missing engines/voices and runtime errors retain readable text. Playback stops on new replies, recording start, panel close and widget cleanup. Spoken responses are capped at 4000 characters; full text remains readable.

Official API: https://doc.qt.io/qtforpython-6/PySide6/QtTextToSpeech/QTextToSpeech.html

Two synthetic tests failed before implementation, then passed: text fallback and playback replacement/close. The development environment exposes SAPI; audio quality, real microphone overlap, normal Home/F12 geometry, focus behavior and packaged speech plugin availability remain live/build acceptance gates. No real patient reply was played, no source instance restarted, no production build produced. The existing local control server is unavailable as documented in the previous receipt. A synthetic offscreen preview verified panel bounds, but the headless Qt platform rendered missing-font boxes even with an explicit Segoe UI family. Text legibility therefore remains a live Windows gate; this preview is not a visual pass.


## Installer provisioning follow-up

Both canonical installer backends now include the shared ensure_english_voice.ps1 and execute it hidden before the optional app launch, including silent setup. Thin ARM/WOA wrappers inherit the change. Existing English System.Speech/SAPI voices are detected before modifying Windows; only a missing English voice triggers the official en-US TextToSpeech capability installation with NoRestart. Windows Update availability and system policy can prevent provisioning. A sanitized status file under ProgramData/AIPacs/installer records ready, restart-needed or unavailable; text replies remain available. This is not an offline bundled Microsoft voice distribution and does not guarantee every Windows edition supplies SAPI voices after capability installation. No voice registry copying or language-setting changes are performed.

PyInstaller now explicitly includes the QtTextToSpeech Python binding and texttospeech plugin directory. Nuitka forces the same binding and requests texttospeech plugins through its PySide6 plugin. These are source packaging changes; no new installer has been built or qualified on a clean end-user machine. Two fail-before packaging guards pass; PowerShell parser reports no syntax errors. Frozen engine discovery and real installed playback remain required release gates.
