# Match exact reviewed Developer source and private config before GUI launch.
function Assert-EagleDeveloperTarget {
    param(
        [Parameter(Mandatory=$true)][string]$ExpectedSource,
        [Parameter(Mandatory=$true)][string]$ExpectedConfig,
        [Parameter(Mandatory=$true)][string]$ServiceCommand
    )
    $command=$ServiceCommand.Replace('\','/').ToLowerInvariant()
    $script=($ExpectedSource.TrimEnd('/','\')+'/tools/eagle_eye/windows_service.py').Replace('\','/').ToLowerInvariant()
    $config=$ExpectedConfig.Replace('\','/').ToLowerInvariant()
    foreach($target in @($script,$config)) {
        $pattern='(?:^|\s)"'+[regex]::Escape($target)+'"(?=\s|$)'
        $unquoted='(?:^|\s)'+[regex]::Escape($target)+'(?=\s|$)'
        if($command -notmatch $pattern -and $command -notmatch $unquoted) {
            throw 'Developer source and active Eagle Eye service do not match. The service update is pending. No GUI was started and no service was restarted.'
        }
    }
}
