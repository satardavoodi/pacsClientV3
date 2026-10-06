from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]

def test_speech_runtime_is_in_both_builds():
    hook=(ROOT/'builder/hooks/_hook_helpers.py').read_text()
    assert '"texttospeech"' in hook
    assert '"PySide6.QtTextToSpeech"' in hook
    assert '"PySide6.QtTextToSpeech"' in (ROOT/'builder nuitka/AIPacs_nuitka.spec.py').read_text()
    assert '--include-qt-plugins=texttospeech' in (ROOT/'builder nuitka/build_nuitka_release.py').read_text()

def test_installers_prepare_voice_before_launch():
    for relative in ('builder/installer/AIPacs_Setup.iss','builder nuitka/installer/AIPacs_Nuitka_Setup.iss'):
        script=(ROOT/relative).read_text()
        assert 'ensure_english_voice.ps1' in script
        assert script.index('Parameters: "-NoProfile') < script.index('Filename: "{app}\\AIPacs.exe"; Description:')
    voice=(ROOT/'builder/installer/ensure_english_voice.ps1').read_text()
    assert 'Language.TextToSpeech~~~en-US~0.0.1.0' in voice
    assert '-NoRestart' in voice
    assert 'GetInstalledVoices' in voice
