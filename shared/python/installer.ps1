# ---------------------------------------------------------------------------
# Windows : installe le Python 3.11 autonome partagé par les applications de Rexo dans
# <hub>\.outils\python (python-build-standalone, empreinte SHA-256 épinglée), comme
# installer.sh sous macOS. Chaque application crée ensuite son propre environnement.
# Relançable : ne retélécharge rien si la bonne version est déjà là.
#   powershell -ExecutionPolicy Bypass -File shared\python\installer.ps1
# ---------------------------------------------------------------------------
$ErrorActionPreference = 'Stop'
$hub = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$dest = Join-Path $hub '.outils\python'
$release = '20261021'
$version = '3.11.17'
$url = "https://github.com/astral-sh/python-build-standalone/releases/download/$release/cpython-$version%2B$release-x86_64-pc-windows-msvc-install_only.tar.gz"
$sha = '136bbb2e50fe037fd5e32126e70e95b35d1fa5dac5bd04a55b8088415ee99540'

if ($env:PROCESSOR_ARCHITECTURE -ne 'AMD64') { throw 'Version figée pour Windows 64 bits (x86_64).' }

$py = Join-Path $dest 'python.exe'
if ((Test-Path $py) -and ((& $py -c 'import platform; print(platform.python_version())') -eq $version)) {
    Write-Output "Python $version déjà installé ($dest)."
    exit 0
}
New-Item -ItemType Directory -Force -Path (Join-Path $hub '.outils') | Out-Null
$tmp = Join-Path $hub ".outils\python-$version.tar.gz.part"
Write-Output "Téléchargement de Python $version…"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$ProgressPreference = 'SilentlyContinue'          # sinon Invoke-WebRequest est très lent
Invoke-WebRequest -Uri $url -OutFile $tmp -UseBasicParsing
if ((Get-FileHash -Algorithm SHA256 $tmp).Hash.ToLower() -ne $sha) {
    Remove-Item -Force $tmp
    throw 'Empreinte SHA-256 incorrecte : refusé.'
}
$neuf = Join-Path $hub '.outils\python.new'
if (Test-Path $neuf) { Remove-Item -Recurse -Force $neuf }
New-Item -ItemType Directory -Path $neuf | Out-Null
tar -xzf $tmp -C $neuf                             # tar.exe est fourni avec Windows 10
if ($LASTEXITCODE -ne 0) { throw 'Archive illisible.' }
if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
Move-Item (Join-Path $neuf 'python') $dest
Remove-Item -Force $neuf, $tmp
Write-Output ("Python " + (& $py -c 'import platform; print(platform.python_version())') + " installé ($dest).")
