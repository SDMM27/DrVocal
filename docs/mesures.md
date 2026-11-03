# Mesures

Cibles : veille < 2 % du processeur total, < 300 Mo de RAM, < 1 faux reveil par heure de discussion.

## Mot de reveil en veille

Commande : `uv run python tools/measure_idle.py --minutes 60` (micro reel, Discord en jeu).
Ajouter `--silent` pour un flux de silence sans micro.

| Date | Source | Duree | Processeur (% total) | RAM max | Faux reveils |
|---|---|---|---|---|---|
| 2026-11-03 19:03 | flux silencieux, modele `salut_doc_vocal`, seuil 0,9 | 10 min | 0,25 % | 213 Mo | 0 |

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
## "salut doc vocal" sur la vraie voix, 2026-11-03

Source : `tools/train_wake.py "salut doc vocal" --recordings data/voice/wake/salut_doc_vocal --max-index 55 --negative-recordings data/voice/negative --exclude-negatives message_vocal le_doc_est_la salut_les_gars on_a_gagne --out models/wake_voice --no-eval`, puis `tools/eval_voice.py --models models/wake_sdv` (dossier contenant ce seul modele). 40 epoques sur processeur.

Prises : 80 de la phrase, 5 de chacune des 19 phrases pieges (3 pour `bonjour` et `le_docteur_est_parti`, de la session precedente). Micro Realtek integre, niveau faible : crete mediane vers 2000/32767, la moitie des prises en dessous.

Protocole :
- Entrainement : prises 000-055 (`052` ecartee, quasi muette), x10 puis augmentees, plus les voix Piper ; 71 negatifs reels en negatifs difficiles (toutes les phrases pieges sauf les 4 du test, dont `salut_doc`, `doc`, `vocal`, `salut_docteur`, `docteur`).
- Validation (choix du seuil) : prises 056-067 (12) ; 114 negatifs synthetiques (voix et phrases jamais entrainees).
- Test : prises 068-079 (12) et 20 negatifs reels jamais entendus (`message_vocal`, `le_doc_est_la`, `salut_les_gars`, `on_a_gagne`, 5 prises chacun). Lu une seule fois, seuil fixe d'avance.

Validation :

| Seuil | Detections | Faux reveils (114 negatifs synthetiques) |
|---|---|---|
| 0,3 | 10/12 | 18 |
| 0,5 | 9/12 | 15 |
| 0,7 | 8/12 | 13 |
| **0,9 (choisi)** | 7/12 | 8 |

Seuil choisi : 0,9, celui qui donne le moins de faux reveils (meme regle qu'a la mesure precedente).

Test, prises tenues a part :

| Seuil | Detections | Faux reveils (20 negatifs reels) |
|---|---|---|
| 0,3 | 9/12 | 1 (`message_vocal`) |
| 0,5 | 8/12 | 1 |
| 0,7 | 6/12 | 1 |
| **0,9 (choisi)** | **6/12** | **1** |

Diagnostic : 39/55 sur les prises d'entrainement a 0,9 (88/95 a la mesure des quatre phrases) : moins de memorisation, mais le classifieur n'apprend pas bien la phrase.

Verdict : insuffisant pour le mode `voice`. Une phrase sur deux n'est pas reconnue au seuil retenu, et les faux reveils sur les negatifs synthetiques restent nombreux (8 sur 114 clips). Les 20 negatifs reels ne suffisent pas a juger la cible « < 1 faux reveil par heure ». Le mode `key` reste le defaut. Pistes, a trancher par l'utilisateur : reenregistrer avec un gain de micro plus haut (ou le micro de jeu), essayer Porcupine (meme protocole `WakeDetector`), ou garder la touche.

## Transcription, 2026-11-03

Source : `tools/bench_stt.py` (fixtures de synthese `tests/fixtures`, 2 phrases), PC de l'utilisateur, 16 coeurs logiques, aucun jeu lance.

| Modele | Appareil | Latence | RAM ajoutee | Exactitude |
|---|---|---|---|---|
| small | cpu | 1,43 s (1er appel 17,8 s) | 327 Mo | 1/2 |
| medium | cpu | 5,02 s (1er appel 22,4 s) | 769 Mo | 1/2 |
| large-v3-turbo | cpu | 6,64 s (1er appel 29,1 s) | 817 Mo | 1/2 |
| tous | cuda | indisponible (`cublas64_12.dll` manquant) | | |

Lecture : `small` sur processeur reste le seul choix raisonnable sans carte graphique, mais depasse la cible de 1 s. L'exactitude sur 2 phrases de synthese ne dit rien de la vraie voix. Reglage garde : `stt_model = "small"`, `stt_device = "cpu"`. A trancher en jeu (Tache 12) : installer les bibliotheques CUDA 12 pour essayer la carte graphique (au risque de prendre des ressources au jeu), ou accepter ~1,4 s. Le premier appel (chargement, 18 s) doit se faire au demarrage, pas a la premiere commande.

## Patience du reveil (trames d'affilee), 2026-11-03

Contexte : en usage reel (seuil 0,5 puis 0,7), des bips de reveil sans que l'utilisateur parle, souvent avec de la musique sur les haut-parleurs. Source : `models/wake/salut_doc_vocal.onnx` diffuse par trames de 80 ms (12 trames de silence avant et apres) sur les prises reelles 056-079 (24, jamais entrainees) et les 91 negatifs reels de `data/voice/negative` (une partie a servi de negatifs difficiles a l'entrainement : chiffres optimistes).

| Seuil | 1 trame | 2 trames d'affilee | 3 trames d'affilee |
|---|---|---|---|
| 0,5 | 22/24, 2 faux | 21/24, 0 faux | 18/24, 0 faux |
| 0,7 | 22/24, 2 faux | 21/24, 0 faux | 18/24, 0 faux |
| 0,9 | 21/24, 2 faux | 21/24, 0 faux | 18/24, 0 faux |

Choix : `patience = 2` (160 ms au-dessus du seuil) dans `WakeDetector`, seuil 0,7. Chaque reveil est journalise avec son score. Non mesure : musique et discussion reelles sur une heure.

Note : `tests/test_wake.py::test_detects_wake_fixture` (lent) echoue depuis le modele entraine sur la vraie voix : la fixture de synthese (voix Piper) plafonne a 0,47, avec ou sans patience.

## Reveils sur le souffle du micro, 2026-11-03

Constat en usage : 3 reveils en 15 s (scores 0,71 ; 0,82 ; 1,00) sans que l'utilisateur parle. Les captures de diagnostic qui suivent sont du souffle (RMS 16-170, aucune trame de parole pour Silero). Rejouees dans `openwakeword.Model`, elles montent a 0,78 (3 trames >= 0,7) ; amplifiees x3, elles retombent a 0,64 au plus : le modele a appris le niveau de bruit du micro de l'utilisateur, present dans tous les positifs et absent de la plupart des negatifs (voix de synthese).

Correctif : chaque reveil est confirme par Silero sur les 1,6 s precedentes (au moins 240 ms de parole, `speech_confirmer`), sinon il est ecarte et journalise. Sur les prises reelles 056-079 a 0,7 avec patience 2 : 21/24 reveils avec ou sans confirmation ; 0 faux reveil sur les 91 negatifs reels dans les deux cas. Le souffle seul, rejoue dans un detecteur neuf, ne declenche pas : en direct, le declenchement depend de l'audio precedent. Correctif de fond a faire : reentrainer avec quelques minutes de souffle et de bruit de la piece en negatifs.

## Noms d'artistes, faisceau et modeles, 2026-11-03

Source : capture reelle « lance MC Pao fausse richesse sur Spotify » (micro Realtek, niveau faible), `temperature=0`, processeur, int8.

| Modele | Faisceau | Duree | Transcription |
|---|---|---|---|
| small | 1 | 1,7 s | Lance MCPOW FOSS RICESSE sur Spotify |
| small | 5 | 1,7 s | Lance MCPOW, fausse richesse sur Spotify. |
| medium | 5 | 4,9 s | Lance MC Pao fausse richesse sur Spotify |
| large-v3-turbo | 5 | 7,0 s | Lance MCPAO fausses richesses sur Spotify. |

Choix : `beam_size = 5` avec `small` (meme duree sur cet ordre). La recherche Spotify trouve « Fausse Richesse » a partir des transcriptions beam 5, pas a partir de beam 1. Piste suivante : `large-v3-turbo` sur la carte graphique (RTX 4060, 8 Go), a mesurer en jeu.
