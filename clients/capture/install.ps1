param([string]$Python = '', [string]$Scheme = 'route-ovs', [string]$InstallDirectory = '')
$ErrorActionPreference = 'Stop'
if ($Scheme -notmatch '^route-ovs(-[a-z0-9]+)?$') { throw 'Invalid protocol name' }
if (-not $InstallDirectory) { $InstallDirectory = Join-Path $env:LOCALAPPDATA 'route-ovs\capture-launcher' }
$destination = [IO.Path]::GetFullPath($InstallDirectory)
New-Item -ItemType Directory -Path $destination -Force | Out-Null
foreach ($name in @('launcher.py','remote_relay.py','configure.ps1','README.md')) {
  $source = Join-Path $PSScriptRoot $name
  $target = Join-Path $destination $name
  if ([IO.Path]::GetFullPath($source) -ne [IO.Path]::GetFullPath($target)) { Copy-Item -LiteralPath $source -Destination $target -Force }
}
$bundle = Join-Path $PSScriptRoot 'route-ovs-capture.exe'
if (-not (Test-Path -LiteralPath $bundle)) { $bundle = Join-Path $PSScriptRoot 'dist\route-ovs-capture.exe' }
if (Test-Path -LiteralPath $bundle) {
  $executable = Join-Path $destination 'route-ovs-capture.exe'
  if ([IO.Path]::GetFullPath($bundle) -ne [IO.Path]::GetFullPath($executable)) { Copy-Item -LiteralPath $bundle -Destination $executable -Force }
  $command = '"{0}" "%1"' -f $executable
} else {
  if (-not $Python) {
    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($py) { $Python = & $py.Source -3 -c 'import sys; print(sys.executable)' }
    else {
      $candidate = Get-Command python.exe -ErrorAction SilentlyContinue
      if ($candidate -and $candidate.Source -notlike '*\WindowsApps\*') { $Python = $candidate.Source }
    }
  }
  if (-not $Python -or -not (Test-Path -LiteralPath $Python)) { throw 'Install Python 3.10+, then run install.ps1 -Python C:\path\python.exe; or use a client package containing route-ovs-capture.exe.' }
  $executable = [IO.Path]::GetFullPath($Python)
  $windowless = Join-Path ([IO.Path]::GetDirectoryName($executable)) 'pythonw.exe'
  if (Test-Path -LiteralPath $windowless) { $executable = $windowless }
  $command = '"{0}" "{1}" "%1"' -f $executable, (Join-Path $destination 'launcher.py')
}
$key = "HKCU:\Software\Classes\$Scheme"
$existing = Get-ItemProperty -LiteralPath "$key\shell\open\command" -ErrorAction SilentlyContinue
if ($existing -and $existing.'(default)' -ne $command) { throw "Protocol $Scheme already has another handler. Existing registration was preserved." }
New-Item -Path "$key\shell\open\command" -Force | Out-Null
Set-Item -LiteralPath $key -Value 'URL:route-ovs capture'
New-ItemProperty -LiteralPath $key -Name 'URL Protocol' -Value '' -PropertyType String -Force | Out-Null
Set-Item -LiteralPath "$key\shell\open\command" -Value $command
Write-Host "Installed $Scheme protocol for the current user. Click Capture in the Web workbench to configure SSH locally."
Write-Host "Launcher: $destination"
