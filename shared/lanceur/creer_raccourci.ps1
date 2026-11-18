# ---------------------------------------------------------------------------
# Windows : raccourci sur le Bureau pour une application web du hub (équivalent de
# creer_app.sh sous macOS).
#   powershell -ExecutionPolicy Bypass -File shared\lanceur\creer_raccourci.ps1 identite
#   powershell -ExecutionPolicy Bypass -File shared\lanceur\creer_raccourci.ps1 reveal
#
# Un double-clic lance shared\lanceur\lancer.py par le pythonw.exe de l'application (aucune
# fenêtre de console) : le serveur local démarre, la page s'ouvre dans le navigateur.
# Le bouton « Quitter » de la page arrête le serveur. Icône dessinée par icone.py, rangée
# dans %LOCALAPPDATA%\Rexo. Relançable : remplace le raccourci existant.
# ---------------------------------------------------------------------------
param([Parameter(Mandatory = $true)][ValidateSet('identite', 'reveal')][string]$appli)
$ErrorActionPreference = 'Stop'
$hub = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$noms = @{ identite = 'Rexo ID'; reveal = 'Rexo Reveal' }
$nom = $noms[$appli]
$venv = Join-Path $hub "apps\$appli\.venv\Scripts"
$pythonw = Join-Path $venv 'pythonw.exe'
if (-not (Test-Path $pythonw)) { throw "Environnement absent : $venv (voir le README de l'application)" }

$icones = Join-Path $env:LOCALAPPDATA 'Rexo'
New-Item -ItemType Directory -Force -Path $icones | Out-Null
$ico = Join-Path $icones "$appli.ico"
& (Join-Path $venv 'python.exe') (Join-Path $hub 'shared\lanceur\icone.py') $appli $ico
if ($LASTEXITCODE -ne 0) { throw 'Icône : échec.' }

$bureau = [Environment]::GetFolderPath('Desktop')
$lnk = Join-Path $bureau "$nom.lnk"
$shell = New-Object -ComObject WScript.Shell
$r = $shell.CreateShortcut($lnk)
$r.TargetPath = $pythonw
$r.Arguments = '"' + (Join-Path $hub 'shared\lanceur\lancer.py') + '" ' + $appli
$r.WorkingDirectory = $hub
$r.IconLocation = "$ico,0"
$r.Description = $nom
$r.Save()
Write-Output "Raccourci créé : $lnk"
