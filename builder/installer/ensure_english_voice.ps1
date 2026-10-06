# Install only the official English Windows speech capability when absent.
$ErrorActionPreference = 'Stop'
$voiceLogDirectory = Join-Path $env:ProgramData 'AIPacs\installer'
New-Item -ItemType Directory -Path $voiceLogDirectory -Force | Out-Null
$voiceLogFile = Join-Path $voiceLogDirectory 'english-voice-status.txt'
function Test-EnglishVoice {
    Add-Type -AssemblyName System.Speech
    $voiceSynthesizer = New-Object System.Speech.Synthesis.SpeechSynthesizer
    try {
        return @($voiceSynthesizer.GetInstalledVoices() | Where-Object {
            $_.Enabled -and $_.VoiceInfo.Culture.TwoLetterISOLanguageName -eq 'en'
        }).Count -gt 0
    } finally { $voiceSynthesizer.Dispose() }
}
try {
    if (Test-EnglishVoice) {
        'English voice already available.' | Set-Content -LiteralPath $voiceLogFile
        exit 0
    }
    $voiceCapabilityName = 'Language.TextToSpeech~~~en-US~0.0.1.0'
    $voiceCapability = Get-WindowsCapability -Online -Name $voiceCapabilityName
    if ($voiceCapability.State -ne 'Installed') {
        $voiceInstallResult = Add-WindowsCapability -Online -Name $voiceCapabilityName -NoRestart
        if ($voiceInstallResult.RestartNeeded) {
            'Windows requests a restart to finish English voice installation.' | Set-Content -LiteralPath $voiceLogFile
            exit 0
        }
    }
    if (Test-EnglishVoice) {
        'English voice ready.' | Set-Content -LiteralPath $voiceLogFile
    } else {
        'Speech capability installed; English SAPI voice not yet available. Text responses remain available.' | Set-Content -LiteralPath $voiceLogFile
    }
} catch {
    'English voice installation unavailable. Check Windows Update or install English speech in Windows Settings. Text responses remain available.' | Set-Content -LiteralPath $voiceLogFile
}
# Voice provisioning never prevents the workstation installation or reboots Windows.
exit 0
