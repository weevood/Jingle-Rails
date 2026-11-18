# Documentation technique — Jingle Rails

## Architecture

- `jingle_rails/core.py` : règles horaires, validation des paramètres et encodage des messages LEGO, testables sans matériel.
- `jingle_rails/__main__.py` : CLI, client Bluetooth BLE, événements, reconnexion et arrêt dans les blocs `finally`.
- `jingle_rails/audio.py` : petite mélodie originale synthétisée localement en WAV temporaire et jouée en boucle avec ALSA `aplay` tant que le train roule.
- `config.example.toml` : valeurs publiques par défaut. Les paramètres réels (notamment adresse Bluetooth) vivent dans `config.local.toml` **ignoré par Git**.
- `tests/` et `.github/workflows/test.yml` : tests automatisés Python.
- `scripts/deploy.sh` et `systemd/` : vérification régulière de `origin/main`, tests de la prochaine version dans une archive et redémarrage du service.

## Protocole Bluetooth

LEGO Powered Up 88009 ; caractéristique GATT `00001624-1212-efde-1623-785feabcd123`.

Trame `08 00 81 PP 11 51 00 VV` : port output (0x81), WriteDirectModeData (0x51), port `PP` (A=0, B=1), niveau signé `VV` en mode 0 ; zéro arrête le moteur. Source : [protocole officiel LEGO](https://lego.github.io/lego-ble-wireless-protocol-docs/).

Le moteur LEGO 88011 **ne donne pas de distance de trajet ni de nombre de tours**. Un tour est estimé par le temps `seconds_per_lap` (15 secondes provisoirement, avant calibration) ; le train peut dériver de son point d'arrêt avec l'usure des piles. Il faut surveiller le dispositif.

## Comportement de l'horloge

- Heure locale du Pi, idéalement `Europe/Zurich` (`timedatectl`).
- Départs HH:00 de 07:00 à 22:00 inclus ; HH:30 de 07:30 à 21:30.
- Nombre de tours = `heure % 12`, avec zéro interprété comme douze.
- Départ dans les quinze premières secondes du créneau seulement ; aucun rattrapage tardif.
- Les créneaux sont marqués avant de démarrer pour éviter un doublon après une interruption.
- Phares à 30 % au repos entre 17:00 et 22:00, 100 % pendant l'animation ; autres moments 0 % au repos.
- Musique générée dans le Pi et répétée sans dépendance réseau. Elle s'arrête quand le trajet se termine.

## Sécurité et limites

- Le hub doit être allumé physiquement et son autonomie dépend des piles.
- En cas de perte Bluetooth, un arrêt moteur **n'est pas garanti**. Prévoir un accès physique immédiat au bouton/piles.
- Arrêt par rampe de puissance, sans retour capteur ni stationnement exact.
- La durée maximale d'un trajet est de 240 secondes par défaut : un carillon trop long est refusé.
- La sortie audio ALSA doit être vérifiée sur le matériel ; absence d'audio ne bloque pas le moteur.
- Les tests CI simulent la logique, **pas** un hub réel. Le déploiement exige un essai sur place.

## Déploiement automatique

Le Raspberry conserve un clone local dans `/home/pi/Jingle-Rails`. `jingle-rails-update.timer` déclenche `scripts/deploy.sh` environ toutes les cinq minutes.

1. Verrou via `flock` ; aucune mise à jour si des fichiers versionnés ont été modifiés localement.
2. `git fetch origin main`, préparation du nouveau commit dans une archive temporaire.
3. `pytest` + `compileall` sur cette archive **avant modification de l'application**.
4. `git merge --ff-only`, puis `systemctl restart jingle-rails.service`.
5. Si le service échoue à redémarrer, retour à l'ancien commit et nouvel essai de redémarrage.

Le script n'interroge **pas encore** les statuts GitHub Actions, et `systemctl active` ne garantit pas la connexion effective au hub : cela constitue une amélioration à prévoir. La mise à jour ne change jamais `config.local.toml`.

## Vérifications

```bash
cd /home/pi/Jingle-Rails
.venv/bin/python -m pytest -q
git log -1 --oneline
systemctl list-timers 'jingle-rails*'
journalctl -u jingle-rails.service -n 80 --no-pager
journalctl -u jingle-rails-update.service -n 80 --no-pager
```

## Prochaines évolutions

Capteur de passage pour compter réellement les tours ; interface web locale ; départ manuel et arrêt d'urgence ; état du hub et niveau des piles ; scénarios multiples et choix de mélodies.

## Journal de décisions

2026-11-18 : dépôt public `Jingle-Rails`. Horloge de 7 h à 22 h, animations aux heures et demi-heures, mélodie originale sur Raspberry, paramètres locaux non publiés et déploiement par `systemd` après tests.

## Diagnostic BLE : hub qui s'éteint

Si `lights-test` termine sur `org.bluez.Error.Failed: Not connected` et que le voyant du hub clignote puis s'éteint :

1. Désactiver le service automatique pour qu'il ne monopolise pas le hub.
2. Vérifier les piles et fermer les autres contrôleurs LEGO.
3. Redémarrer le hub, puis lancer `python -m jingle_rails ble-hold` : le programme maintient une connexion pendant 20 secondes **sans envoyer aucune commande aux ports** et vérifie la stabilité.
4. Si ce test réussit, lancer `lights-test` : séquence prudente 10 %, 30 %, 10 %, 0 % sur le port d'éclairage seulement.
5. Comparer le résultat. Une déconnexion pendant `ble-hold` indique que le problème n'est pas lié aux commandes d'éclairage. Une déconnexion uniquement sous `lights-test` justifie de vérifier les piles, les accessoires et les trames/événements BLE.

La commande `lights-test` ne commande jamais le moteur. Lorsqu'un hub est déconnecté, le programme journalise qu'un arrêt ne peut pas être garanti plutôt que d'empiler les erreurs. Aucun comportement du hub n'est garanti tant que les tests physiques n'ont pas été validés.

### Correctif du 18 novembre — diagnostic distinct des deux erreurs

- `ble-hold` restait connecté 20 s, mais la fermeture automatique de Bleak/BlueZ pouvait lever `EOFError`. `hub_connection` encapsule désormais l'ouverture et la fermeture et journalise spécifiquement cette erreur de nettoyage, sans masquer une erreur pendant l'envoi.
- `lights-test` n'utilise provisoirement que 10 % et 30 % et trace `client.is_connected` après chaque écriture. Cela ne constitue **pas** une correction de l'origine de la déconnexion : il faut confirmer les résultats sur le hub.
- Poursuivre avec piles récentes, aucune application LEGO connectée et service Jingle Rails désactivé. Tant que la liaison n'est pas stable, ne pas lancer le moteur.
