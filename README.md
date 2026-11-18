# 🚂 Jingle Rails — le train de Noël qui donne l'heure

Le **LEGO Holiday Train 10254** devient une horloge de Noël vivante. Un Raspberry Pi commande le hub Powered Up en Bluetooth : le train allume ses phares, démarre en douceur, fait ses tours et joue une petite mélodie **originale**, sans smartphone ni cloud.

## 🎄 Le spectacle

| Quand ? | Que se passe-t-il ? |
|---|---|
| **7 h à 22 h, à chaque heure pile** | Les phares s'allument, le train effectue autant de tours que l'heure sur une horloge à 12 heures (7 h → 7 tours, midi → 12 tours, 13 h → 1 tour, 22 h → 10 tours). Musique pendant le trajet. |
| **7 h 30 à 21 h 30** | Trois clignotements, puis un tour de circuit en musique. |
| **17 h à 22 h** | Phares à 30 % à l'arrêt, 100 % pendant le voyage. |
| **La nuit** | Repos, lumières éteintes. |

> ⚠️ Le moteur 88011 ne mesure pas les tours. Nous chronométrons un tour sur ton circuit, puis multiplions cette durée. L'arrêt n'est donc pas garanti au centimètre. Surveille les premiers essais.

## 🔧 Matériel

- Hub LEGO Powered Up **88009**, moteur train **88011** (port **A**) et lumières **88005** (port **B**).
- Raspberry Pi Bluetooth avec Raspberry Pi OS et Python **3.11+**.
- Haut-parleur configuré sur le Pi (USB, HDMI ou jack selon le modèle). La musique est synthétisée localement et diffusée par `aplay`.

## 🚀 Installation sur le Raspberry

Exemple pour un utilisateur `pi` sous `/home/pi` (sinon adapter les chemins du service) :

```bash
cd /home/pi
git clone https://github.com/weevood/Jingle-Rails.git
cd Jingle-Rails
bash scripts/install.sh
```

Allume le hub, ferme l'application LEGO sur le téléphone, puis :

```bash
.venv/bin/python -m jingle_rails scan
nano config.local.toml
```

Copie l'adresse Bluetooth détectée dans `hub_address`. **Ce fichier est privé, ignoré par Git**. Régle également `seconds_per_lap` après calibration et, si tu le souhaites, `music_volume` ou `music_enabled`.

### Tester avant d'automatiser

Place le train sur un circuit dégagé, sous surveillance :

```bash
.venv/bin/python -m jingle_rails music-test
.venv/bin/python -m jingle_rails lap-test --seconds 5
.venv/bin/python -m jingle_rails hour-test --hour 3
```

Le test de 5 secondes aide à évaluer le temps nécessaire à un tour. Il ne modifie pas la calibration automatiquement. Avec 15 secondes par tour provisoirement, le trajet le plus long (12 tours) dure environ 180 secondes. La durée maximale d'un trajet est limitée à 240 secondes par défaut.


### Le hub doit-il être rallumé chaque matin ?

Non, **si le hub reste allumé et la connexion Bluetooth maintenue**. Le Raspberry conserve la connexion même la nuit (aucune circulation entre 22 h et 7 h). Il demande régulièrement le niveau de batterie du hub (`keepalive_seconds = 60`) pour tester un maintien en éveil, sans commander le moteur. Il s'agit d'une **hypothèse à vérifier sur le matériel**, pas d'une garantie officielle LEGO. Un hub complètement éteint ne peut pas être réveillé par Bluetooth avec son firmware d'origine.

Sans circuit, tester pendant 15 minutes :

```bash
sudo systemctl stop jingle-rails.service jingle-rails-update.timer
.venv/bin/python -m jingle_rails idle-test --minutes 15
```

Le test doit afficher les réponses batterie et confirmer une connexion toujours active. Si le hub s'éteint, consulter [la documentation technique](docs/TECHNIQUE.md) : aucune commande de réveil à distance ne peut alors être envoyée.

### Démarrer le service

```bash
sudo systemctl enable --now jingle-rails.service jingle-rails-update.timer
systemctl status jingle-rails.service --no-pager
journalctl -u jingle-rails.service -f
```

Arrêt : `sudo systemctl stop jingle-rails.service`. **En cas de train incontrôlé, coupe le hub physiquement** : un ordre BLE peut être perdu. Le Pi ne peut pas rallumer un hub LEGO éteint.

## 🔄 Le workflow GitHub → Raspberry

```text
Tu demandes une évolution
       ↓
Code poussé sur GitHub
       ↓
GitHub Actions lance les tests
       ↓
Le Pi consulte origin/main toutes les ~5 minutes
       ↓
Il teste la nouvelle version dans une copie
       ↓
Mise à jour puis redémarrage du service
       └─ retour à l'ancien commit si le service ne démarre pas
```

Le Raspberry continue de fonctionner sans connexion Internet. **À ce stade, le Pi vérifie ses tests locaux, mais ne bloque pas sur le statut de GitHub Actions ;** on pourra durcir ce contrôle par la suite. Les tests logiciels ne remplacent pas les essais réels avec le train.

## 🔒 Dépôt public, configuration privée

- Aucun identifiant, adresse Bluetooth, adresse privée ou jeton n'est publié.
- Les réglages propres à l'installation restent dans `config.local.toml` (ignoré via `.gitignore`).
- Le Pi lit ce dépôt public sans jeton GitHub.
- La musique est une composition créée pour le projet, sans contenu audio tiers.

## 👩‍💻 Développer

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

Les explications du protocole BLE, du déploiement, des limites de sécurité et des décisions techniques sont dans [la documentation technique](docs/TECHNIQUE.md).

*Projet personnel non affilié à LEGO.*
