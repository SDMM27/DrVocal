# Mesures

Cibles : veille < 2 % du processeur total, < 300 Mo de RAM, < 1 faux reveil par heure de discussion.

## Mot de reveil en veille

Commande : `uv run python tools/measure_idle.py --minutes 60` (micro reel, Discord en jeu).
Ajouter `--silent` pour un flux de silence sans micro.

| Date | Source | Duree | Processeur (% total) | RAM max | Faux reveils |
|---|---|---|---|---|---|
| | | | | | |

## Conditions de la mesure reelle

- Jeu :
- Discussion Discord (nombre de personnes) :
- Modele(s) de reveil et seuil :
- Faux reveils (heure, ce qui se disait) :

## Decision du point de controle

- [ ] Cibles atteintes : on continue avec openWakeWord.
- [ ] Sinon : essayer Porcupine (meme protocole `WakeDetector`), puis une touche a maintenir. Prevenir l'utilisateur avant de changer de moteur.
