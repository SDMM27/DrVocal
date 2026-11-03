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

## Mot de reveil sur la vraie voix, 2026-11-03

Sources : `tools/train_wake.py` (entrainement), `tools/eval_voice.py` (mesure). Quatre modeles ensemble (`salut_docteur`, `bonjour_docteur`, `bungiorno_docteur`, `priviet_docteur`) dans le vrai `WakeDetector`, chaque WAV diffuse par trames de 80 ms avec 12 trames de silence avant et apres. Un positif n'est detecte que si un reveil tombe pendant le fichier ; un faux reveil est tout reveil sur un negatif (silence ajoute compris).

Protocole :
- Entrainement : prises 000-023 de chaque phrase (une prise quasi muette ecartee : `bungiorno_docteur/002`), x10 puis augmentees, plus les voix Piper et les negatifs synthetiques existants. Negatifs reels en negatifs difficiles : 8 phrases x 3 prises (`bonjour`, `bonjour_tout_le_monde`, `salut_mon_pote`, `bien_joue_docteur`, `passe_la_balle`, `je_vais_au_but`, `attention_derriere_toi`, `on_a_gagne`).
- Validation (choix du seuil) : prises 024-031 (8 par phrase, 32 en tout), jamais dans l'ajustement ; negatifs = 102 clips synthetiques (voix et phrases d'evaluation jamais entrainees).
- Test : prises 032-039 (8 par phrase, 32 positifs) et 12 negatifs reels jamais entendus (`salut`, `docteur`, `salut_les_gars`, `le_docteur_est_parti`, 3 prises chacun). Lu une seule fois, avec le seuil fixe d'avance.
- Seuil choisi sur la validation : 0,9 (aucun seuil n'annule les faux reveils ; 0,9 est celui qui en donne le moins, 29 sur 102 contre 61 a 0,3, pour 13/32 detections contre 15/32). Le seuil 0,5 par defaut n'a pas ete retenu.
- Duree d'entrainement : 412 s (salut, cache de synthese reutilise), 924 s, 1066 s, 926 s, soit environ 55 min au total sur processeur. Le cache des etapes `neg` et `noise` de salut a ete copie pour les trois autres phrases (independantes de la phrase).

Test, prises tenues a part (32 positifs, 12 negatifs) :

| Seuil | salut | bonjour | bungiorno | priviet | Total detecte | Faux reveils (12 negatifs) |
|---|---|---|---|---|---|---|
| 0,3 | 5/8 | 3/8 | 6/8 | 3/8 | 17/32 | 7 |
| 0,5 | 5/8 | 3/8 | 6/8 | 2/8 | 16/32 | 7 |
| 0,7 | 5/8 | 3/8 | 6/8 | 2/8 | 16/32 | 6 |
| **0,9 (choisi)** | 5/8 | 2/8 | 6/8 | 2/8 | **15/32** | **6** |

Faux reveils a 0,9 par negatif reel : `docteur` 3 (3 prises sur 3), `le_docteur_est_parti` 3 (3 sur 3), `salut` 0, `salut_les_gars` 0. Par modele : salut 5, bonjour 3, priviet 3, bungiorno 1.

Croisement a 0,9 (modele, phrase prononcee) : le modele `salut_docteur` se declenche sur bungiorno 2/8, priviet 1/8 ; `bungiorno_docteur` sur salut 1/8 ; `bonjour_docteur` sur salut 4/8 ; `priviet_docteur` sur salut 1/8. Les modeles se confondent surtout avec `salut`, et tous reagissent au mot « docteur ».

Diagnostics : sur les prises d'entrainement (en echantillon) la detection est de 88/95 a 0,9, contre 13/32 sur la validation : le modele memorise les prises, il ne generalise pas avec 23-24 prises par phrase. Sur la validation, les faux reveils sur les negatifs synthetiques sont aussi nombreux (29 sur 102 a 0,9).

Verdict : insuffisant. Moins de la moitie des phrases dites sont reconnues et le mot « docteur » seul reveille. Limites de cette mesure : 8 prises par phrase et 12 negatifs (4 phrases) ne permettent pas de valider la cible « < 1 faux reveil par heure » ; l'intervalle de confiance sur 15/32 est tres large, et 12 negatifs d'une seconde ne couvrent aucune heure de discussion. Seule une vraie session (une heure de jeu avec discussion Discord) peut verifier cette cible. Sur ces chiffres, on ne peut pas conclure que ce modele atteindra la cible, ni que openWakeWord est exclu : le goulot est le jeu de donnees reel et le classifieur surajuste.

## Modele synthetique "salut doc vocal", 2026-11-03

Source : `tools/train_wake.py "salut doc vocal"`, voix Piper seules (aucun enregistrement reel), 40 epoques sur processeur. Evaluation integree au script : voix jamais entrainees (fr_FR-tom-medium et locuteurs MLS d'evaluation), 598 s de negatifs synthetiques.

| Seuil | Positifs propres | Positifs bruites | Faux reveils (598 s) | Faux reveils par heure |
|---|---|---|---|---|
| 0,5 | 13/24 | 15/24 | 14 | 84 |
| 0,7 | 10/24 | 12/24 | 10 | 60 |
| 0,9 | 8/24 | 10/24 | 8 | 48 |

Verdict : modele provisoire, insuffisant pour le mode `voice`. Il sert a verifier la chaine de bout en bout ; le mode `key` (touche a maintenir) reste le defaut. Prochaine mesure : avec les 80 prises reelles et les negatifs pieges de `tools/record_voice.py`.