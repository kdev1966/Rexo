#!/bin/bash
# ---------------------------------------------------------------------------
# Crée une application macOS (double-clic) pour une application web du hub :
#   shared/lanceur/creer_app.sh identite      -> ~/Applications/Identité.app
#   shared/lanceur/creer_app.sh reveal        -> ~/Applications/Reveal.app
#   ... --bureau                              -> et un raccourci sur le Bureau
#
# L'application démarre le serveur local (127.0.0.1 seulement), ouvre la page dans le
# navigateur par défaut, la rouvre si on clique sur son icône dans le Dock, et arrête le
# serveur quand on la quitte (Cmd+Q). Si le serveur tourne déjà, elle ouvre seulement la page.
# Journal du serveur : ~/Library/Logs/RetoHub/<application>.log
# Icône dessinée par icone.py (Pillow de l'application). Relançable : remplace l'application
# existante. Rien n'est installé hors de ~/Applications (et du raccourci sur le Bureau).
# ---------------------------------------------------------------------------
set -euo pipefail
HUB="$(cd "$(dirname "$0")/../.." && pwd)"
case "${1:-}" in
  identite) NOM="Identité"; MODULE="identite.interface"; PORT=8766 ;;
  reveal)   NOM="Reveal";   MODULE="reveal.interface";   PORT=8765 ;;
  *) echo "usage : $0 identite|reveal" >&2; exit 1 ;;
esac
APP_DIR="$HUB/apps/$1"
[ -x "$APP_DIR/.venv/bin/python" ] || { echo "environnement absent : $APP_DIR/.venv (voir le README de l'application)" >&2; exit 1; }
DEST="$HOME/Applications/$NOM.app"
LOGS="$HOME/Library/Logs/RetoHub"
mkdir -p "$HOME/Applications" "$LOGS"
SCRIPT="$(mktemp -t lanceur).applescript"
trap 'rm -f "$SCRIPT"' EXIT
cat > "$SCRIPT" <<APPLESCRIPT
property adresse : "http://127.0.0.1:$PORT/"
property pid : ""

on run
	try
		do shell script "curl -s -o /dev/null --max-time 1 " & adresse
		-- déjà lancé (autre fenêtre, terminal) : on ouvre seulement la page
	on error
		set pid to do shell script "cd " & quoted form of "$APP_DIR" & " || exit 1; nohup .venv/bin/python -m $MODULE < /dev/null > " & quoted form of "$LOGS/$1.log" & " 2>&1 & echo \$!"
		repeat 40 times
			try
				do shell script "curl -s -o /dev/null --max-time 1 " & adresse
				exit repeat
			on error
				delay 0.25
			end try
		end repeat
	end try
	open location adresse
end run

on reopen
	open location adresse
end reopen

on quit
	if pid is not "" then
		try
			do shell script "kill " & pid
		end try
	end if
	continue quit
end quit
APPLESCRIPT
rm -rf "$DEST"
osacompile -s -o "$DEST" "$SCRIPT"

# Icône : PNG 1024 -> jeu de tailles -> .icns, à la place de celle d'AppleScript
ICONES="$(mktemp -d -t icone)"
trap 'rm -f "$SCRIPT"; rm -rf "$ICONES"' EXIT
"$APP_DIR/.venv/bin/python" "$HUB/shared/lanceur/icone.py" "$1" "$ICONES/icone.png"
mkdir "$ICONES/icone.iconset"
for t in 16 32 128 256 512; do
  sips -z $t $t "$ICONES/icone.png" --out "$ICONES/icone.iconset/icon_${t}x${t}.png" >/dev/null
  sips -z $((t * 2)) $((t * 2)) "$ICONES/icone.png" --out "$ICONES/icone.iconset/icon_${t}x${t}@2x.png" >/dev/null
done
iconutil -c icns "$ICONES/icone.iconset" -o "$DEST/Contents/Resources/applet.icns"
codesign --force --sign - "$DEST" 2>/dev/null       # signature locale, à refaire après modification
touch "$DEST"
echo "$DEST créée : double-cliquer pour lancer $NOM, Cmd+Q pour l'arrêter."

if [ "${2:-}" = "--bureau" ]; then
  ln -sfn "$DEST" "$HOME/Desktop/$NOM"
  echo "Raccourci sur le Bureau : $HOME/Desktop/$NOM"
fi
