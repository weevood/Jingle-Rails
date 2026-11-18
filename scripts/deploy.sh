#!/usr/bin/env bash
# Déploiement local automatique depuis un dépôt public, sans secret GitHub.
set -Eeuo pipefail
BASE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$BASE"
exec 9>"$BASE/.deploy.lock"
flock -n 9 || exit 0
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "Refus : fichiers versionnés modifiés localement" >&2
  exit 1
fi
git fetch --quiet origin main
CURRENT="$(git rev-parse HEAD)"
NEXT="$(git rev-parse origin/main)"
[[ "$CURRENT" == "$NEXT" ]] && exit 0

# Tester une copie propre du prochain commit AVANT de remplacer le programme actif.
STAGING="$(mktemp -d)"
trap 'rm -rf "$STAGING"' EXIT
git archive "$NEXT" | tar -x -C "$STAGING"
"$BASE/.venv/bin/python" -m pytest -q "$STAGING/tests" -o pythonpath="$STAGING"
"$BASE/.venv/bin/python" -m compileall -q "$STAGING/jingle_rails"

# Le service doit être installé et pourra être redémarré sans mot de passe via sudoers restreint.
git merge --ff-only --quiet origin/main
if ! sudo -n systemctl restart jingle-rails.service; then
  echo "Échec du redémarrage : retour au commit précédent" >&2
  git reset --hard "$CURRENT"
  sudo -n systemctl restart jingle-rails.service || true
  exit 1
fi
sleep 3
if ! systemctl is-active --quiet jingle-rails.service; then
  echo "Service inactif : retour au commit précédent" >&2
  git reset --hard "$CURRENT"
  sudo -n systemctl restart jingle-rails.service || true
  exit 1
fi
echo "Déployé : $NEXT"
