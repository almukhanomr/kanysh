#Requires -Version 5.1
<#
Starts an already installed Kanysh Basic environment in WSL on this Windows workstation.
Does not install drivers, alter WSL settings, start remote compute or expose a public endpoint.
Prepared launcher; execution on Windows/WSL has not yet been validated.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^/')]
    [string]$LinuxProjectPath,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^/')]
    [string]$StateDirectory,

    [string]$Distribution = 'Ubuntu',
    [ValidateSet('agent', 'full')]
    [string]$McpProfile = 'agent',
    [string]$DataDirectory,
    [string]$SourceName = 'geology',
    [ValidateRange(1, 65535)]
    [int]$Port = 8765
)

$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Run this launcher on Windows with WSL 2 configured.' }
Get-Command wsl.exe -ErrorAction Stop | Out-Null

# Only the local service token is explicitly forwarded, never printed or passed in argv.
$taskPreviousWslEnv = $env:WSLENV
try {
    if ($env:OPENSUBSURFACE_TOKEN) {
        $taskForwardedNames = @($taskPreviousWslEnv, 'OPENSUBSURFACE_TOKEN') | Where-Object { $_ }
        $env:WSLENV = $taskForwardedNames -join ':'
    }
    $taskServiceArgs = @('--distribution', $Distribution, '--cd', $LinuxProjectPath,
        '--exec', '.venv/bin/kanysh-basic', '--home', $StateDirectory)

    & wsl.exe @taskServiceArgs doctor
    if ($LASTEXITCODE -ne 0) { throw 'doctor failed; check the WSL project path and Python 3.12 environment.' }

    if ($DataDirectory) {
        $taskResolvedFolder = (Resolve-Path -LiteralPath $DataDirectory).ProviderPath
        $taskLinuxFolder = & wsl.exe --distribution $Distribution --exec wslpath -a -u $taskResolvedFolder
        if ($LASTEXITCODE -ne 0 -or @($taskLinuxFolder).Count -ne 1 -or $taskLinuxFolder -notmatch '^/') {
            throw 'Could not translate the data folder to a WSL path.'
        }
        $taskRegistrationArgs = $taskServiceArgs + @('source-add', $SourceName, $taskLinuxFolder.Trim())
        & wsl.exe @taskRegistrationArgs
        if ($LASTEXITCODE -ne 0) { throw 'Source registration failed.' }
    }

    Write-Host "Local MCP endpoint: http://127.0.0.1:$Port/mcp/"
    Write-Host 'Keep this process running. Closing the chat does not stop jobs; stopping this service does.'
    $taskLaunchArgs = $taskServiceArgs + @('serve', '--no-ui', '--mcp-profile', $McpProfile, '--port', [string]$Port)
    & wsl.exe @taskLaunchArgs
    if ($LASTEXITCODE -ne 0) { throw 'Kanysh Basic stopped with an error.' }
}
finally {
    $env:WSLENV = $taskPreviousWslEnv
}
