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

### Analyse du trafic HCI et mise à jour Bleak (18 novembre 2026)

Une capture `btmon` a confirmé trois trames GATT écrites vers le port B : `080081011151000a` (10 %), `080081011151001e` (30 %), puis `080081011151000a` (10 %). La commande 0 % n'était pas visible dans cette capture. Le contrôleur du Pi a ensuite demandé la déconnexion HCI (`0x13`, puis événement `0x16`) ; ce fait ne prouve pas que la déconnexion est la cause plutôt qu'une conséquence de l'échec applicatif.

Le Pi était sur Bleak 2.1.1 / dbus-fast 5.2.0 / BlueZ 5.82, Python 3.13. Les notes de Bleak **3.1.0 (2026-11-07)** indiquent un correctif explicite pour `disconnect()` levant un `EOFError` sur BlueZ. `requirements.txt` exige donc Bleak >=3.1,<4 ; une installation existante doit exécuter explicitement `.venv/bin/python -m pip install -r requirements-dev.txt` pour mettre le venv à jour, puisque le déploiement Git ne met pas les dépendances à jour automatiquement.

Procédure : arrêter service et timer, faire le `git pull`, actualiser les dépendances, lancer `pytest`, puis `ble-hold` et enfin `lights-test` avec piles fiables. Ne pas activer la circulation automatique avant validation physique.

### Révision du contrôleur LWP3 (18 novembre 2026)

**Défaut de notre implémentation identifié :** les commandes port output portaient le byte `0x11` (« execute immediately + command feedback »), mais le contrôleur ne s'abonnait pas aux notifications de la caractéristique LEGO. Il ne pouvait donc pas recevoir les retours du hub `0x82` ni les éventuels événements d'erreur `0x05`.

- Correction : `BleakClient.start_notify(CHARACTERISTIC, hub_notification)` après connexion et avant toute commande de port.
- Correction : `write_gatt_char(..., response=True)` au lieu des écritures sans réponse, la caractéristique annonçant bien le support GATT Write et le document officiel LEGO décrivant l'usage de Write With Response dans son profil 3.x. L'accusé GATT ne doit pas être confondu avec le retour LWP3 `0x82`.
- Les notifications de commande et les erreurs du hub sont maintenant journalisées.
- La trame `08 00 81 01 11 51 00 VV` elle-même était valide pour la lumière branchée sur le port B.

**Hypothèse encore à confirmer :** ce protocole de connexion incomplet explique la déconnexion répétée après la première commande. Il faut valider sur le 88009 réel ; les tests unitaires ne simulent pas la radio.

Référence : [LEGO Wireless Protocol 3.x officiel](https://lego.github.io/lego-ble-wireless-protocol-docs/) — « LEGO Specific GATT Service », « Startup and Completion Information » et « Port Output Command Feedback ».

### Validation matérielle des phares (18 novembre 2026)

Après abonnement GATT et écritures avec accusé, le test réel `lights-test` a successivement accepté 10 %, 30 %, 10 %, 0 %, avec quatre retours LWP3 `(port=1, flags=0x0a)`. Le champ `0x0a` est un **bitfield de retour de commande**, et non la luminosité en pourcentage. La déconnexion à la fin de la session est attendue. Les 13 tests logiciels sur le Pi ont réussi. Prochaine étape : tester le moteur sur support avec roues libres ; ne pas activer le mode automatique tant que l'arrêt du moteur n'est pas validé.

### Validation matérielle du scénario complet (18 novembre 2026)

Sur Raspberry Pi 4 `piscreen`, Python 3.13, BlueZ 5.82 et Bleak 3.1.0 :

- `lights-test` : quatre commandes de phares confirmées et retours de commande reçus.
- `lap-test --seconds 2` : moteur effectivement en mouvement pendant deux secondes et arrêt confirmé physiquement lors de deux essais.
- `test` : scénario d'un tour nominal de 15 s réalisé ; accélération et décélération clairement perceptibles ; aucun échec Bluetooth pendant le scénario. La fermeture BLE finale est attendue.
- **Non encore vérifiés** : sens de rotation, durée réelle d'un tour sur les rails, arrêt au même emplacement, scénarios de l'heure et de la demi-heure en situation réelle, autonomie et exécution continue 7 h–22 h.

Attention : le temps écoulé observé entre le départ du scénario et l'arrêt est légèrement supérieur aux 15 s nominaux, car les écritures GATT et les temporisations de la rampe ajoutent de la latence. Ne pas assimiler `seconds_per_lap=15` à une mesure précise du temps réel en circulation. Recalibrer sur circuit assemblé avant de démarrer le service automatique.

La musique demeure désactivée dans la configuration locale en attendant une sortie audio.

### Maintien du hub éveillé entre les horaires (18 novembre 2026)

Le problème de l'allumage manuel est distinct de l'ordonnancement. Avec son firmware LEGO, un hub éteint **ne peut pas être réveillé à distance par BLE**. La connexion doit donc rester ouverte 24 h/24, avec moteur coupé la nuit.

Le mode `run` conserve déjà sa connexion GATT entre les animations. Nouvelle mesure expérimentale : toutes les 60 secondes, envoyer une requête standard **Hub Property / Battery Voltage / Request Update** : `05 00 01 06 05`. La propriété et la requête sont documentées officiellement dans LEGO Wireless Protocol 3.0 ; **leur efficacité comme keepalive n'est pas garantie** par LEGO. Les notifications en retour sont décodées si disponibles. Aucun ordre moteur ou lumière n'est envoyé par ce mécanisme.

Validation sans circuit : laisser le hub allumé, désactiver le service automatique puis lancer `python -m jingle_rails idle-test --minutes 15`. Confirmer que le voyant reste allumé et que le processus termine sans erreur. Pour une vraie autonomie, tester également après une nuit entière (avec le circuit posé et service en fonctionnement supervisé). Si le hub s'éteint malgré la connexion, le Raspberry ne peut pas le rallumer avec le firmware d'origine ; Pybricks ou une solution matérielle pourront être étudiés.

Références : [documentation du protocole LEGO](https://lego.github.io/lego-ble-wireless-protocol-docs/) ; [pylgbst issue #125](https://github.com/undera/pylgbst/issues/125) décrivant des extinctions après ~10 minutes en Python malgré des exécutions plus longues avec l'application officielle.

### Validation matérielle de l'inactivité avec interrogation batterie (18 novembre 2026)

Essai sur le hub 88009 avec `idle-test --minutes 15` de **10:46:27 à 11:01:29** :

- Notifications activées, connexion Bluetooth maintenue et voyant du hub allumé pendant les 15 minutes.
- Requête batterie `05 00 01 06 05` toutes les 60 secondes, 15 réponses indiquant 100 %.
- Aucune perte de connexion ni erreur pendant le test ; déconnexion normale à la fermeture du programme.
- Aucun mouvement moteur ni allumage des phares demandé durant ce mode.
- **Portée du résultat** : intervalle de 60 secondes validé sur 15 minutes seulement, pas encore validé plusieurs heures ni pendant une nuit. Le 100 % reporté par le hub n'est pas une mesure de capacité utile restante ni une estimation d'autonomie.
- **Choix utilisateur confirmé** : préserver l'éclairage des phares à 30 % entre 17 h et 22 h dans le mode normal `run`.

Prochaine étape : test longue durée du mode repos, puis calibration du circuit et validation du service automatique ; ne pas activer les horaires tant que les rails ne sont pas montés.
