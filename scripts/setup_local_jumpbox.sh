#!/bin/bash
set -euo pipefail

# Controller synchronizes the local fork first. Never clone/pull upstream here.
cd /home/vagrant/GOAD
test -f .goad-source-manifest.json
test -f ansible/build.yml
sudo apt-get update
sudo apt-get install -y python3-venv python3-pip
python3 -m pip install -r requirements.yml
cd ansible
/home/vagrant/.local/bin/ansible-galaxy install -r requirements.yml
