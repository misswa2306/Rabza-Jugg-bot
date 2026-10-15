# Rabza Jugg Bot

Bot Telegram de mini-jeu textuel fictif à Montréal. Les actions, gains et risques
sont simulés et ne constituent pas des instructions pour agir dans la vraie vie.

## Prérequis

- Python 3.10 ou plus récent
- Un bot créé avec [@BotFather](https://t.me/BotFather) et son token

## Installation et lancement (Windows PowerShell)

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:TELEGRAM_BOT_TOKEN = "TOKEN_FOURNI_PAR_BOTFATHER"
python bot.py
```

Le fichier SQLite `rabza_jugg_bot.sqlite3` est créé automatiquement au premier
lancement. Pour choisir un autre chemin, définis `DATABASE_PATH`.

## Installation et lancement (macOS/Linux)

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN="TOKEN_FOURNI_PAR_BOTFATHER"
python bot.py
```

Ne publie jamais le token dans le code ou dans un dépôt.

## Commandes

- `/start` — inscription et accueil
- `/profil` — cash, gamos, heat et statut
- `/jugg` — menu des actions du mini-jeu
- `/top` — classement des dix joueurs les plus riches
- `/prison` — temps restant et option de caution (300$)

## Tests

```powershell
python -m unittest discover -s tests -v
```
