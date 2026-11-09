# Dr Vocal

Assistant vocal local, en français, pour joueur PC sous Windows 11. Il se pilote à la voix pendant une partie, sans alt-tab : Spotify, Discord, prise de notes et sessions Claude Code (facultatif). Usage personnel, un seul utilisateur.

La conception complète (objectifs, anti-objectifs, décisions) est dans `docs/superpowers/specs/2026-11-02-dr-vocal-design.md`.

## Ce que fait Dr Vocal

- **Spotify** (compte Premium) : lance un titre, un album, un artiste ou une playlist par son nom ; pause, reprise, suivant, précédent, volume.
- **Discord** via un bot personnel : écrire un message dans un salon, se déplacer dans un salon vocal, muter un autre membre (mute serveur), se muter ou se mettre en sourdine.
- **Notes** : le texte dicté est enregistré mot pour mot dans un nouveau fichier `.txt` daté.
- **Claude Code** (facultatif) : un prompt dicté lance une session Claude Code en arrière-plan, sur ton abonnement, dans le dossier d'un projet que tu nommes ; « importe mes sessions Claude » les ouvre ensuite dans l'app Claude.

Tout est local : réveil, détection de fin de phrase, transcription (faster-whisper), compréhension (règles, sans réseau ni modèle de langage) et voix (Piper). Seules les actions Spotify, Discord et Claude Code passent par le réseau, et seulement après un réveil.

## Ce que Dr Vocal ne fait pas

- Il ne supprime aucun fichier et ne ferme ni le jeu ni Discord : ces actions n'existent pas dans son catalogue. Seules les actions enregistrées sont exécutables.
- Il n'écrase jamais une note : chaque note crée un nouveau fichier.
- Il n'écrit pas sur Discord depuis ton compte (pas de selfbot) : les messages paraissent sous le nom du bot.
- Il ne converse pas librement : il exécute des actions, et tout échange ouvert passe par Claude Code.
- Il ne parle pas par défaut, pour ne pas couvrir le jeu.
- Il ne fonctionne que sous Windows, pour un seul utilisateur.
- **Aucun raccourci clavier n'est simulé par défaut** (`simulated_hotkeys_enabled = false`). Simuler des touches (`SendInput`) pendant qu'un jeu est au premier plan peut être vu comme de l'automatisation par un anti-cheat (la règle de CS2 est large, et des faux positifs sont rapportés). Le risque n'est pas écarté par les sources consultées : voir `docs/anti-triche.md` avant d'activer l'option. Par défaut, tu te mutes via le bot Discord (qui doit être configuré, et tu dois être dans un salon vocal). Le mode « touche à maintenir » lit seulement l'état d'une touche et n'envoie rien au jeu.

## Prérequis et installation

- Windows 11, Python 3.12 ou plus récent, [uv](https://docs.astral.sh/uv/).
- Un micro. Le micro est partagé avec Discord : tes amis entendent ce que tu dis à Dr Vocal.
- Facultatif, pour Claude Code : Claude Code installé et connecté (`claude` dans le PATH, sinon `claude_command` dans `config.toml`), et chaque projet ouvert une fois dans Claude Code pour qu'il soit de confiance. Sans Claude Code, ou sans projet valide, les commandes Claude sont désactivées.

```powershell
git clone https://github.com/SDMM27/DrVocal.git
cd DrVocal
uv sync
```

Pour le bot Discord (facultatif) : `uv sync --extra discord`.

Vérifications de développement (lancées aussi par la CI) : `uv run ruff check .`, `uv run pyright`, `uv run pytest -m "not slow"`.

### Voix Piper

La voix qui lit les messages Discord n'est pas dans le dépôt. Télécharger la voix par défaut dans `models/piper` :

```powershell
uv run python -m piper.download_voices fr_FR-siwis-medium --data-dir models/piper
```

### Autres modèles

- **Transcription** : le modèle faster-whisper (`stt_model`, `small` par défaut) est chargé à la première transcription et téléchargé par faster-whisper s'il est absent du cache. Prévoir une connexion pour le premier lancement.
- **Détection de fin de phrase** : le modèle Silero est livré avec faster-whisper, rien à installer.
- **Mot de réveil vocal** : modèles `*.onnx` dans `models/wake` (mode `voice` uniquement). Voir la section « Entraîner le mot de réveil ». Sans eux, ou en mode `key`, rien à faire.

### Configuration

Copier le modèle de configuration (`config.toml` est ignoré par git) :

```powershell
Copy-Item config.example.toml config.toml
```

Les identifiants secrets vont dans un fichier `secrets.toml` à la racine, lui aussi ignoré par git :

```toml
spotify_client_id = "..."
discord_bot_token = "..."
```

Sans `config.toml`, Dr Vocal démarre avec les réglages par défaut (journalisé en avertissement). Sans `secrets.toml`, Spotify et Discord sont simplement absents.

## Configuration

Tous les réglages sont dans `config.toml` (modèle : `config.example.toml`). Une valeur invalide empêche le démarrage (erreur dans le journal).

### Réveil

| Réglage | Défaut | Rôle |
|---|---|---|
| `wake_mode` | `"key"` | `"key"` : tu maintiens une touche ou un bouton pour parler. `"voice"` : mot de réveil. Toute autre valeur est une erreur. |
| `push_to_talk_key` | `"mouse5"` | Touche ou bouton à maintenir en mode `key` : `mouse3`, `mouse4`, `mouse5`, une lettre ou un chiffre, `F1` à `F24`, `space`, `enter`, `tab`, `esc`, `backspace`, `insert`, `delete`, `home`, `end`, `pageup`, `pagedown`, flèches (`left`, `up`, `right`, `down`). Choisir une touche non utilisée en jeu. |
| `wake_phrases` | `["salut doc vocal"]` | Phrases d'activation, en minuscules. Liste lue par la configuration ; chaque phrase vocale demande son propre modèle `.onnx`. |
| `wake_models_dir` | `"models/wake"` | Dossier des modèles `*.onnx`, relatif à la racine du projet. Tous les `.onnx` du dossier sont chargés ensemble. Sans modèle, Dr Vocal journalise une erreur et se rabat sur la touche. |
| `wake_threshold` | `0.9` | Seuil de détection du mot de réveil (voir `docs/mesures.md`). |

### Voix, transcription, notes, écran

| Réglage | Défaut | Rôle |
|---|---|---|
| `tts_voice` | `"models/piper/fr_FR-siwis-medium.onnx"` | Voix Piper, relatif à la racine. |
| `stt_model` | `"small"` | Modèle faster-whisper. Le banc d'essai `tools/bench_stt.py` compare `small`, `medium` et `large-v3-turbo`. |
| `stt_device` | `"cpu"` | `cpu` ou `cuda`. Sur CPU, le jeu garde la carte graphique. |
| `notes_dir` | `Documents/NOTES` | Dossier des notes (créé au besoin). |
| `second_screen_index` | `1` | Index du second écran (0 = écran principal). Si cet écran n'existe pas, la fenêtre reste masquée plutôt que de recouvrir le jeu. |

### Projets, synonymes, sons

```toml
[projects]
"Dr Vocal" = "D:/NasaCode/DrVocal"   # nom parlé -> dossier ; les noms sont mis en minuscules

[synonyms]
"balance la suivante" = "musique suivante"   # phrase dite -> phrase canonique (énoncé entier)

[sounds]   # facultatif : WAV personnalisés, sinon bips intégrés
wake = "C:/Users/moi/sons/wake.wav"
```

Noms de sons reconnus : `wake` (début d'écoute), `success`, `failure`, `done` (Claude a fini). Un nom inconnu ou un fichier illisible est journalisé et ignoré. Les chemins relatifs sont résolus depuis la racine du projet.

Un projet doit figurer dans `[projects]` pour que Claude Code puisse y travailler ; sinon aucune session n'est lancée.

### Discord

Dr Vocal utilise un **bot personnel**, jamais ton compte (Discord interdit l'automatisation d'un compte utilisateur).

1. Sur le [portail développeur Discord](https://discord.com/developers/applications), créer une application, puis un bot. Copier son jeton dans `secrets.toml` (`discord_bot_token`). Ne jamais le partager.
2. Dans la page du bot, activer le **Server Members Intent**. Le bot n'utilise pas l'intent Message Content et n'écoute aucun message.
3. Inviter le bot sur tes serveurs avec le lien suivant (remplacer `<APPLICATION_ID>` par l'identifiant de l'application). Les permissions demandées (`30411776`) sont : View Channels, Send Messages, Mute Members, Deafen Members, Move Members, Connect.

   ```text
   https://discord.com/oauth2/authorize?client_id=<APPLICATION_ID>&scope=bot&permissions=30411776
   ```

4. Activer le mode développeur de Discord (Paramètres, Avancés), puis clic droit sur ton profil, « Copier l'identifiant ». C'est ton `owner_id`.

```toml
[discord]
owner_id = 123456789012345678   # ton identifiant utilisateur

[discord.channels]   # nom parlé -> identifiant du salon
general = 123456789012345678

[discord.members]    # nom parlé -> identifiant du membre
alex = 123456789012345678
```

Le bot n'est activé que si `discord_bot_token` **et** `owner_id` sont renseignés ; il n'agit que dans les serveurs où tu es membre. Sans entrée dans `[discord.channels]` ou `[discord.members]`, le nom dit doit correspondre exactement (casse et accents ignorés) à celui du salon ou du membre. Plusieurs correspondances : rien n'est fait.

Se déplacer de salon et se muter demandent d'être déjà dans un salon vocal.

### Spotify

Spotify demande un compte **Premium** pour le contrôle de lecture.

1. Sur le [tableau de bord développeur Spotify](https://developer.spotify.com/dashboard), créer une application.
2. Ajouter exactement cette URI de redirection : `http://127.0.0.1:8888/callback`.
3. Copier le Client ID dans `secrets.toml` (`spotify_client_id`). Aucun secret client n'est nécessaire (authentification PKCE).
4. Autoriser l'application une fois, avant d'utiliser la voix : `uv run python tools/spotify_login.py`. Le navigateur s'ouvre (permissions `user-read-playback-state`, `user-modify-playback-state`, `user-follow-read`, `user-top-read`, `playlist-read-private`, `user-library-read`, `user-read-recently-played`, `user-library-modify`, `playlist-modify-private` et `playlist-modify-public`) ; le script affiche ensuite le nombre d'artistes, de playlists et de titres de ta bibliothèque. Le jeton est gardé dans `.spotify-cache` à la racine, ignoré par git. Sans cette étape, le navigateur s'ouvre au premier ordre Spotify.

**Bibliothèque prioritaire** : avant toute recherche, « mets… » compare ce que tu dis à tes artistes suivis, tes playlists, tes titres likés, tes écoutes récentes et tes plus écoutés (artistes et titres), jusqu'à 1000 titres likés. Un artiste écouté sans être suivi y entre aussi, et un titre se dit avec ou sans son artiste (« Mc Pao fausse richesse »). Elle se charge en arrière-plan au démarrage et se recharge toutes les heures ; les titres exigent une correspondance plus proche que les artistes. Un nom approximatif suffit (la transcription déforme souvent les noms : « d'Ariano » joue Daryana). Sans correspondance, la recherche Spotify classique prend le relais.

**Playlists générées par Spotify** (« En boucle », Daily Mix, Découvertes de la semaine…) : l'API ne les voit pas en mode développement (absentes de ta bibliothèque et de la recherche), mais Spotify sait les lire par leur adresse. Lance-en une dans Spotify, puis dis « retiens cette playlist sous le nom En boucle » (ou « enregistre cette playlist comme… », « appelle cette playlist… ») : Dr Vocal garde l'adresse de ce qui joue dans `spotify_aliases.json` (dossier de données) et « lance ma playlist en boucle » fonctionne aussitôt. Même chose avec « ce morceau », « cet album » ou « cet artiste ». « Ma playlist X » ne cherche jamais dans le catalogue public : sans correspondance dans ta bibliothèque et tes alias, Dr Vocal le dit au lieu de lancer la playlist d'un inconnu.

**Après une mise à jour** (en particulier celle qui ajoute les likes et l'ajout à une playlist : `user-library-modify`, `playlist-modify-private`, `playlist-modify-public`), relancer `uv run python tools/spotify_login.py` pour réautoriser ; sinon, spotipy refuse l'ancien jeton et le navigateur s'ouvre au premier ordre Spotify.

Dr Vocal vérifie que la lecture démarre vraiment et retente une fois sur l'application du PC sinon.

Si aucun appareil Spotify n'est actif, Dr Vocal retombe sur l'application de ce PC. Si elle est fermée, « mets… » et « reprends la musique » l'ouvrent et attendent jusqu'à 20 s qu'elle soit prête ; les autres ordres (pause, suivant, volume) ne l'ouvrent pas.

### Raccourcis Discord simulés (désactivés par défaut)

```toml
simulated_hotkeys_enabled = false

[discord.hotkeys]
mute = "ctrl+shift+m"
deafen = "ctrl+shift+d"
```

Mettre `simulated_hotkeys_enabled = true` fait envoyer ces combinaisons (déjà configurées dans Discord) par `SendInput` pour « coupe mon micro » et « mets-moi en sourdine ». Dans ce cas, le bot ne gère plus ces deux ordres. **Lire `docs/anti-triche.md` avant d'activer**, surtout pour les jeux avec anti-cheat (CS2, Rocket League en ligne). Le jeu au premier plan reçoit aussi les touches simulées.

## Utilisation

### Lancement

```powershell
uv run python -m drvocal
```

Aucune fenêtre de console n'est nécessaire une fois lancé. Le journal est dans `%LOCALAPPDATA%\DrVocal\drvocal.log` (rotation 1 Mo, 3 sauvegardes). Les transcriptions n'y sont écrites qu'en niveau DEBUG : `$env:DRVOCAL_LOG_LEVEL = "DEBUG"` avant le lancement. Ctrl+C arrête l'assistant.

Les composants optionnels s'activent ainsi ; un échec au démarrage est journalisé et ignoré, le reste continue :

| Composant | Activé par |
|---|---|
| Spotify | `spotify_client_id` dans `secrets.toml` |
| Discord (bot) | `discord_bot_token` dans `secrets.toml` et `[discord] owner_id` non nul |
| Raccourcis clavier simulés | `simulated_hotkeys_enabled = true` |
| Notes, Claude, deuxième écran | toujours |

### Mode touche à maintenir (défaut)

Maintiens la touche ou le bouton (`push_to_talk_key`, `mouse5` par défaut), dis ta demande, relâche. Un petit son confirme le début de l'écoute ; une pression de moins de 0,3 s est ignorée. La capture s'arrête au plus tard après 15 s. Le jeu reçoit toujours la touche : Dr Vocal ne fait que lire son état (voir `docs/anti-triche.md`).

### Mode voix

Avec `wake_mode = "voice"`, dis « salut doc vocal » (ou la phrase de `wake_phrases` pour laquelle tu as un modèle), attends le petit son, puis dis ta demande : la fin de phrase est détectée après 0,7 s de silence. Si aucune parole ne suit dans les 3 s, il retourne en veille sans son. Ce mode demande un modèle entraîné sur ta voix ; les mesures actuelles sont dans `docs/mesures.md`.

### Recommencer une demande

Si tu t'es trompé ou que la réponse tarde, redis le mot de réveil (en mode touche : relâche puis rappuie) pendant l'écoute ou la transcription. La demande en cours est abandonnée, le son de réveil rejoue et Dr Vocal écoute la nouvelle. En mode vocal, redire le mot de réveil en pleine phrase n'interrompt plus l'enregistrement : une fois la phrase transcrite, Dr Vocal garde ce qui suit le mot de réveil s'il le retrouve dans la transcription (et réécoute s'il n'y a rien après), sinon il garde toute la phrase, par exemple quand « Dr Vocal » est le nom d'un projet. Pendant la transcription, le mot de réveil relance toujours. En mode touche, rien ne change : rappuyer abandonne tout de suite. Pendant une dictée de note, le mot de réveil ne fait rien.

### Sons de retour

Réveil : double bip montant. Succès : bip aigu. Échec ou commande non comprise : bip descendant. Claude a fini : bip discret. Rien ne se dit à voix haute sauf pour un message Discord à relire.

### Commandes reconnues

Les commandes sont analysées par des règles (accents et majuscules ignorés), sans interprétation libre. Une phrase non reconnue donne un son d'échec et aucune action. Exemples :

- **Spotify**
  - « mets Daft Punk », « joue Random Access Memories », « lance ma playlist sport »
  - « pause », « mets en pause », « arrête la musique »
  - « reprends la musique », « relance la lecture »
  - « musique suivante », « chanson suivante », « suivant », « passe la musique »
  - « musique précédente », « précédent »
  - « volume 40 » (ou « volume 40 pour cent »)
  - « like ce titre », « ajoute ce titre à mes titres likés », « mets ce titre en favori », « j'aime ce titre » : ajoute le titre en cours à tes titres likés
  - « ajoute ce titre à ma playlist Sport », « mets ce morceau dans ma playlist Sport » : ajoute le titre en cours à la playlist la plus proche ; seules tes propres playlists et les playlists collaboratives sont possibles (pas les alias ni celles des autres), et Dr Vocal dit le nom exact de la playlist choisie
  - « annule », « annule le dernier ajout », « retire-le » : annule le dernier like ou ajout, dans les 2 minutes (une seule fois ; « annule Claude » arrête toujours la session Claude)
  - « retiens cette playlist sous le nom En boucle », « enregistre cette playlist comme Sport », « appelle cet artiste Mon groupe » : mémorise ce qui joue sous ce nom
- **Discord**
  - « coupe mon micro », « mute-moi » ; « mets-moi en sourdine »
  - « écris dans général salut tout le monde » : le message est relu à voix haute, puis envoyé après 4 s sauf si tu dis « annule »
  - « va dans le salon général », « déplace-moi sur jeux »
  - « mute Alex », « coupe le micro de Alex », « rends muet Alex » (mute serveur)
- **Notes**
  - « prends une note », « fais une note », « écris une note » : dicte ensuite ta note ; le silence de fin est plus long (2,5 s). La note est écrite mot pour mot dans `notes_dir`, sous la forme `AAAA-MM-JJ_HH-MM-SS.txt`.
- **Journal**
  - « ouvre le journal », « montre le journal », « affiche le journal », « montre-moi le journal », « ouvre le journal de Dr Vocal » : ouvre la fenêtre du journal (voir plus bas).
- **Claude Code** (seulement si Claude Code est installé et qu'un projet valide est dans `[projects]`)
  - « demande à Claude sur Dr Vocal de lancer les tests » (prépositions acceptées : `sur`, `dans`, `pour`, `avec`) : lance une session en arrière-plan dans ce projet
  - « continue avec Claude pour ajouter un test » : poursuit la session en cours du projet
  - « arrête Claude », « stop Claude », « arrête la session Claude » : interrompt la session en cours
  - « importe mes sessions Claude » : ouvre dans l'app Claude les sessions lancées à la voix
- **Synonymes** : tout énoncé entier défini dans `[synonyms]`.

### Deuxième écran et sessions Claude

Une petite fenêtre, placée sur `second_screen_index` et qui ne prend jamais le focus, affiche les messages de Dr Vocal et de Claude Code (« lancée », « finie », « attend ta réponse », « arrêtée », « N sessions Claude à importer »...) et les erreurs. Elle apparaît quand il y a quelque chose à montrer.

Les sessions Claude Code tournent en arrière-plan, sur ton abonnement, en mode auto (jamais de mode qui contourne les autorisations). Les dossiers trop sensibles (racine d'un lecteur, dossier personnel, AppData, Windows, Program Files) sont refusés comme projets, et un projet doit avoir été ouvert une fois dans Claude Code pour être de confiance : sinon le lancement échoue avec un message qui le dit.

- **Une session à la fois par projet.** Tant qu'elle tourne, un nouveau prompt pour le même projet est refusé (« Claude travaille déjà sur... »).
- **Bip « Claude a fini ».** Il retentit aussi quand Claude attend ta réponse. Le message correspondant s'affiche sur le deuxième écran ; Dr Vocal ne dit rien à voix haute.
- **Import à la demande seulement.** « importe mes sessions Claude » ouvre les sessions dans l'app Claude, ce qui peut prendre le focus : cela n'arrive donc que sur cette commande vocale, jamais tout seul. Au démarrage, Dr Vocal te dit seulement combien de sessions sont à importer.
- **Pas de reprise à la voix après l'import.** Une session déjà importée se continue dans l'app, pas avec « continue avec Claude ».
- **Un worktree par session.** Avant d'écrire, Claude Code crée son propre worktree `.claude/worktrees/<nom>` sur une branche `worktree-<nom>` : les changements se retrouvent dans la session importée, pas directement dans la copie de travail du projet.

## Journal des commandes et vocabulaire

Chaque commande dite après le réveil est notée dans `%LOCALAPPDATA%\DrVocal\commands\commands.jsonl` : date, texte transcrit, action et arguments compris (ou `null` si la commande n'a pas été comprise), succès, durée de transcription et d'action. Le texte comprend donc les messages Discord et les prompts Claude dictés dans la commande. Les dictées de notes ne sont pas journalisées. Le WAV de la commande n'est gardé que pour un échec (non comprise ou action échouée), dans `commandsailures` (200 plus récents). Le fichier tourne à 2 Mo (`commands.1.jsonl`). Tout reste local sur ton PC.

Pour le désactiver : `command_log = false` dans `config.toml`.

Pour rejouer les échecs avec les réglages actuels (nouvelle transcription, nouvelle analyse, comparaison avec l'ancien résultat) :

```powershell
uv run python tools/replay_commands.py --limit 50
uv run python tools/replay_commands.py --no-hotwords   # sans vocabulaire, pour comparer
```

`stt_vocabulary` (liste de noms propres, par exemple `["Dr Vocal", "Daft Punk"]`) aide la transcription à reconnaître des noms mal compris. Ces termes passent avant ceux tirés automatiquement des projets, des salons et membres Discord et de Spotify (~400 caractères au total). `stt_hotwords = false` désactive tout le vocabulaire.

### Fenêtre du journal

La fenêtre « Dr Vocal — journal » affiche en tableau, en lecture seule, ce que Dr Vocal a entendu, compris et fait (les 500 dernières lignes, rafraîchies toutes les 2 s). Pour l'ouvrir : dire « ouvre le journal », ou utiliser un raccourci sur le bureau, créé par :

```powershell
uv run python tools/install_journal_shortcut.py
uv run python tools/install_journal_shortcut.py --remove   # retire le raccourci
```

Le raccourci `Journal Dr Vocal` lance `.venv\Scripts\pythonw.exe -m drvocal.journal` : lancer d'abord `uv sync`. Une seule fenêtre à la fois.

Les filtres en haut : **Tout**, **Pas compris** (phrase entendue mais aucune action reconnue), **Échecs** (action reconnue mais échouée) et **Faux réveils** (réveil écarté faute de parole, ou réveil sans rien entendre ensuite). Le bouton ▶ réécoute l'audio des commandes non comprises ou échouées. Sans `command_log`, le journal reste vide.

## Lancement au démarrage de Windows

Enregistre `pythonw.exe -m drvocal` dans la clé `Run` de l'utilisateur (sans droits administrateur, sans console) :

```powershell
uv run python tools/install_autostart.py
```

Pour le retirer :

```powershell
uv run python tools/install_autostart.py --remove
```

La commande utilise `.venv\Scripts\pythonw.exe` à la racine du projet : lancer d'abord `uv sync`. Le journal est dans `%LOCALAPPDATA%\DrVocal\drvocal.log`.

## Entraîner le mot de réveil sur sa voix

Le mode `voice` demande un modèle openWakeWord par phrase. Un modèle entraîné seulement sur des voix de synthèse est insuffisant ; la procédure ci-dessous ajoute ta vraie voix. Les chiffres obtenus et la décision sont dans `docs/mesures.md` : ils ne sont pas repris ici. Tant que la mesure n'est pas satisfaisante, garde `wake_mode = "key"`.

### 1. Préparer l'entraînement

```powershell
uv sync --group train
```

Voix Piper utilisées pour la synthèse d'entraînement et d'évaluation :

```powershell
foreach ($v in "siwis-medium", "siwis-low", "gilles-low", "upmc-medium", "mls-medium", "tom-medium") {
  uv run python -m piper.download_voices "fr_FR-$v" --data-dir models/piper
}
```

### 2. Enregistrer sa voix

```powershell
uv run python tools/record_voice.py --takes 80
```

Chaque phrase s'affiche : dis-la avant la fin de la barre de progression. 80 prises de « salut doc vocal » (valeur par défaut), puis 5 prises de chacune des phrases proches qui ne doivent pas réveiller (« salut », « doc », « docteur », « message vocal », discussion de jeu ordinaire...). Ctrl+C arrête, et relancer reprend où tu t'étais arrêté. Les prises muettes ou saturées sont refusées et refaites. Tout reste dans `data/voice/` (`wake/<phrase>/NNN.wav` et `negative/<phrase>/NNN.wav`), ignoré par git ; rien ne quitte le PC.

Contrôler les prises sans évaluer :

```powershell
uv run python tools/eval_voice.py --check
```

### 3. Entraîner

Les prises 000 à 055 servent à l'entraînement ; les prises 056 à 067 (validation, choix du seuil) et 068 à 079 (test, à ne regarder qu'une fois) restent à part. Les négatifs réels listés dans `--exclude-negatives` sont réservés à l'évaluation.

```powershell
uv run python tools/train_wake.py "salut doc vocal" `
  --recordings data/voice/wake/salut_doc_vocal --max-index 55 `
  --negative-recordings data/voice/negative `
  --exclude-negatives message_vocal le_doc_est_la salut_les_gars on_a_gagne `
  --out models/wake_voice
```

L'entraînement tourne sur processeur et dure plusieurs minutes (plusieurs dizaines de minutes pour plusieurs phrases). Il écrit `models/wake_voice/salut_doc_vocal.onnx` ; sans `--out`, le modèle va directement dans `models/wake`. Options utiles : `--real-repeat` (surpondération des prises réelles, 10 par défaut), `--epochs` (40), `--eval-only` (évalue le modèle existant sans entraîner), `--no-eval`.

### 4. Évaluer

L'évaluation passe par le vrai `WakeDetector` et diffuse chaque WAV trame par trame, comme à l'exécution.

```powershell
# validation : choisir le seuil
uv run python tools/eval_voice.py --split val --synthetic-negatives

# test : une seule lecture, avec le seuil fixé d'avance et des négatifs jamais entendus
uv run python tools/eval_voice.py --split test --negatives message_vocal le_doc_est_la salut_les_gars on_a_gagne
```

Par défaut, les modèles lus sont ceux de `models/wake_voice` et la phrase évaluée est `salut_doc_vocal` (`--models`, `--phrases`). `--thresholds` change les seuils essayés (0,3 ; 0,5 ; 0,7 ; 0,9 par défaut) et `--json FICHIER` enregistre les résultats.

### 5. Activer

Copier le modèle retenu dans le dossier lu par Dr Vocal, puis passer en mode voix :

```powershell
Copy-Item models/wake_voice/salut_doc_vocal.onnx models/wake/
```

```toml
wake_mode = "voice"
wake_threshold = 0.9   # le seuil retenu à l'évaluation
```

Tous les `.onnx` de `models/wake` sont chargés ensemble : retirer ceux d'anciennes phrases.

### Mesurer le coût en veille

```powershell
uv run python tools/measure_idle.py --minutes 60
```

Micro réel, Discord en jeu ; ajouter `--silent` pour un flux de silence sans micro. Imprime une ligne prête à coller dans `docs/mesures.md` (processeur, RAM, faux réveils). Les cibles sont : moins de 2 % du processeur total, moins de 300 Mo de RAM, moins d'un faux réveil par heure de discussion.

## Autres outils

| Commande | Rôle |
|---|---|
| `uv run python tools/bench_stt.py` | Banc d'essai de la transcription : latence, RAM et exactitude pour `small`, `medium` et `large-v3-turbo`, sur CPU et CUDA, avec les fixtures de `tests/fixtures`. |
| `uv run python tools/make_fixtures.py` | Régénère les WAV de test (16 kHz mono) avec Piper. Demande les voix `fr_FR-siwis-medium` et `fr_FR-tom-medium` dans `models/piper`. |

## Tests

```powershell
uv run pytest
```

Le groupe de dépendances `dev` (pytest, pytest-asyncio, psutil) est installé par `uv sync`. Les tests marqués `slow` chargent un vrai modèle (téléchargement possible, plusieurs secondes). Pour les ignorer :

```powershell
uv run pytest -m "not slow"
```

## Documents

- `docs/superpowers/specs/2026-11-02-dr-vocal-design.md` : conception, objectifs et anti-objectifs.
- `docs/anti-triche.md` : pourquoi les raccourcis simulés sont désactivés.
- `docs/mesures.md` : mesures du mot de réveil, de la transcription et du coût en veille.
