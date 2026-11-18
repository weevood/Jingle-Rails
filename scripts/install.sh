#!/usr/bin/env bash
# À exécuter sur un Raspberry Pi OS comme utilisateur pi.
set -Eeuo pipefail
cd /home/pi/Jingle-Rails
sudo apt-get update
sudo apt-get install -y python3-venv bluez bluetooth alsa-utils
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
if [[ ! -f config.local.toml ]]; then
  cp config.example.toml config.local.toml
  chmod 600 config.local.toml
fi
echo "Configurer /home/pi/Jingle-Rails/config.local.toml avant de démarrer le service."
sudo cp systemd/jingle-rails.service /etc/systemd/system/
sudo cp systemd/jingle-rails-update.service /etc/systemd/system/
sudo cp systemd/jingle-rails-update.timer /etc/systemd/system/
# N'autoriser que le redémarrage du service du train.
echo 'pi ALL=(root) NOPASSWD: /usr/bin/systemctl restart jingle-rails.service' | sudo tee /etc/sudoers.d/jingle-rails >/dev/null
sudo chmod 440 /etc/sudoers.d/jingle-rails
sudo visudo -cf /etc/sudoers.d/jingle-rails
sudo systemctl daemon-reload
sudo systemctl enable jingle-rails-update.timer
echo "OK. Pour lancer : sudo systemctl enable --now jingle-rails.service jingle-rails-update.timer"
