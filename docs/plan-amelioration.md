# Dr Vocal : revue et plan d'amélioration

Date : 2026-11-05. Branche revue : `feat/dr-vocal` (commit `51ec7a8`).

Objectif visé : faire de Dr Vocal **l'assistant vocal de référence des joueurs PC**. Concrètement, il doit :

- s'installer et se configurer en quelques minutes, sans fichier de configuration ;
- comprendre chaque utilisateur du premier coup, même avec le bruit du jeu et de Discord ;
- réagir instantanément ;
- ne jamais se réveiller à tort ;
- ne rien coûter aux performances du jeu ;
- ne faire courir aucun risque (anti-cheat, actions destructrices, fuite de jetons) ;
- être simple à étendre.

## 0. Mode d'emploi de ce document

- Chaque **lot** (section 7) peut être confié seul à une autre conversation. Donner à cette conversation :
  - la section 1 (contexte) ;
  - la section 5 si le lot touche une API tierce ;
  - le lot lui-même.

  Chaque lot liste ses fichiers, ses dépendances et ses critères de fin.
- Deux lots qui touchent les mêmes fichiers sont indiqués comme **séquentiels**. Ne pas les lancer en parallèle.
- Priorités :
  - **P0** : bloquant pour une distribution publique ;
  - **P1** : nécessaire pour être « la référence » ;
  - **P2** : important, mais peut attendre ;
  - **P3** : bonus.
- Effort, pour un développeur :
  - **S** : 2 jours ou moins ;
  - **M** : 3 à 5 jours ;
  - **L** : 1 à 3 semaines ;
  - **XL** : plus de 3 semaines.
- Légende des constats :
  - **[Code]** : observé dans le code ;
  - **[Doc]** : affirmé par le README, la spec ou `docs/mesures.md`, non revérifié ;
  - **[Source]** : vérifié dans une documentation officielle tierce (URL en section 5) ;
  - **[NV]** : non vérifié.

## 1. Contexte en une page

Dr Vocal est un programme Python 3.12 de 3 200 lignes environ (`src/drvocal`), pour Windows 11.

- **Chaîne audio.**
  - Le micro est lu par trames de 80 ms (`audio/mic.py`).
  - Le réveil se fait par touche maintenue (`audio/push_to_talk.py`, mode par défaut) ou par mot de réveil openWakeWord (`audio/wake.py`).
  - La fin de phrase est détectée par Silero VAD (`audio/vad.py`).
  - La transcription utilise faster-whisper `small`, int8, sur processeur (`audio/stt.py`).
- **Compréhension.** Des règles regex en français (`intent.py`) produisent une `Intent`. Elle n'est exécutée que si elle est enregistrée dans un catalogue fermé (`actions.py`, `ACTION_NAMES`).
- **Actions.**
  - Spotify Web API en PKCE (`actions_spotify.py`).
  - Bot Discord personnel (`actions_discord.py`).
  - Raccourcis simulés par SendInput, désactivés par défaut (`actions_hotkeys.py`).
  - Notes `.txt` (`actions_notes.py`).
  - Sessions Claude Code via `claude-agent-sdk`, avec une politique d'outils dans un hook `PreToolUse` (`claude_session.py`, `claude_policy.py`).
- **Interface.**
  - Une fenêtre pywebview sur le deuxième écran, qui ne prend jamais le focus (`screen.py`).
  - Des bips (`audio/sounds.py`).
  - La voix Piper, seulement pour les questions (`audio/tts.py`).
- **Configuration.** `config.toml` et `secrets.toml` à la racine du dépôt, installation par `git clone` puis `uv sync`.

## 2. Méthode et limites de cette revue

**Lu :**

- `README.md` et `config.example.toml` ;
- `docs/superpowers/specs/2026-11-02-dr-vocal-design.md`, `docs/superpowers/plans/2026-11-02-dr-vocal.md`, `docs/anti-triche.md` et `docs/mesures.md` ;
- tout `src/drvocal`, ainsi que `tools/install_autostart.py` et `tools/spotify_login.py` ;
- la liste des tests.

**Exécuté :** `pytest -m "not slow"`. Résultat : **457 passés, 5 désélectionnés (lents), 1 avertissement** (`audioop` déprécié, importé par discord.py). Les tests lents n'ont pas été lancés.

**Recherché :** les conditions d'accès Spotify, Discord, Claude (Agent SDK) et les politiques anti-cheat, dans les sources officielles. Voir la section 5.

**Introuvable :**

- **il n'y a pas de fichier ROADMAP** dans le dépôt. Le plan `docs/superpowers/plans/…` en tient lieu, et aucune de ses 72 cases n'est cochée, alors que les tâches 1 à 11 sont visiblement codées ;
- **il n'y a pas de fichier LICENSE**.

**Non vérifié par moi (à mesurer, pas à croire) :**

- l'impact sur les images par seconde (FPS) ;
- la latence réelle de bout en bout ;
- les faux réveils sur une heure de Discord ;
- le comportement de `os.startfile("spotify:")` vis-à-vis du focus ;
- le fonctionnement réel du bot Discord et de Claude Code sur cette machine ;
- la qualité de transcription sur de vraies voix variées.

## 3. État des lieux

### 3.1 Ce qui marche (et qu'il faut garder)

- **Le catalogue fermé.** Une action absente de `ACTION_NAMES` ne peut pas être enregistrée (`actions.py`). Une phrase non comprise produit un bip d'échec et aucune action. C'est la bonne barrière de sécurité, à conserver telle quelle dans l'architecture d'extension. [Code]
- **Rien n'est transcrit avant le réveil.** `Ears` ne transmet les trames qu'à un écouteur actif ou au détecteur, et ne capture que dans un écouteur (`app.py`). [Code]
- **Le mode touche est passif.** `GetAsyncKeyState` lit l'état de la touche sans hook et sans injection (`audio/push_to_talk.py`). C'est le choix le plus sûr côté anti-cheat. [Code]
- **SendInput est désactivé par défaut**, avec une analyse honnête du risque (`docs/anti-triche.md`). [Code + Doc]
- **La politique Claude échoue en mode fermé.** Une exception dans le hook refuse l'outil. `setting_sources=[]` empêche une règle utilisateur de court-circuiter la politique. Les chemins Windows trompeurs (8.3, ADS, `\\?\`, `D:x`) sont pris en compte. Les commandes demandent toujours un accord, et les commandes destructives reconnues sont refusées (`claude_policy.py`). [Code]
- **La fenêtre du deuxième écran est sûre.**
  - Le HTML est échappé.
  - La CSP utilise un hash au lieu de `unsafe-inline`.
  - Un identifiant en attente ne peut être résolu qu'une fois.
  - La fenêtre a les styles `NOACTIVATE` et `TOOLWINDOW` (`screen.py`). [Code]
- **Spotify est robuste.**
  - La lecture est vérifiée après un `204`.
  - La lecture tente un second essai sur l'appareil local.
  - En cas d'échec, la musique d'avant est remise.
  - Les noms sont rapprochés de la bibliothèque de l'utilisateur.
  - La bibliothèque est préchargée (`actions_spotify.py`). [Code]
- **Le bot Discord est minimal.** Il a des intents réduits, n'écoute aucun message et désactive les mentions. Un message est relu à voix haute avec 4 s pour l'annuler (`actions_discord.py`). [Code]
- **Les notes ne s'écrasent jamais** : ouverture en `"x"` (`actions_notes.py`). [Code]
- **Le micro se reconnecte.** S'il est débranché, il est rouvert toutes les 2 s (`audio/mic.py`). [Code]
- **Le journal est tournant**, et le jeton spotipy est masqué en DEBUG (`__main__.py`). [Code]
- **La discipline de mesure est bonne.** `docs/mesures.md` sépare entraînement, validation et test, et donne des verdicts honnêtes. Les outils `bench_stt.py`, `measure_idle.py` et `eval_voice.py` existent. [Doc]
- **La suite de tests est rapide et verte** (457 tests en 35 s). [Exécuté]

### 3.2 Ce qui est cassé ou non prouvé

| # | Constat | Source |
|---|---|---|
| C1 | **Le mot de réveil est inutilisable.** Sur la meilleure mesure tenue à part, il détecte 6/12, et le modèle n'est entraîné que sur la voix d'une seule personne. Le mode touche est donc le défaut. | [Doc] `docs/mesures.md` |
| C2 | **La latence de transcription est de 1,43 s** (`small`, processeur), pour une cible de 1 s. CUDA est indisponible (`cublas64_12.dll` manquant). | [Doc] |
| C3 | **La validation en jeu (tâche 12) n'a jamais été faite.** Il n'y a aucune mesure de FPS, de latence ou de faux réveils en partie réelle. La section « Conditions de la mesure réelle » de `mesures.md` est vide. | [Doc] |
| C4 | Le test lent `test_wake.py::test_detects_wake_fixture` échoue depuis le modèle sur vraie voix. | [Doc], non relancé |
| C5 | **L'arbre de travail montre 21 fichiers modifiés** qui ne diffèrent que par les fins de ligne (`git diff --ignore-cr-at-eol` est vide). Il n'y a pas de `.gitattributes`. | [Code] |
| C6 | **`Catalogue.run` avale toute exception sans la journaliser** (`actions.py:53`). Les échecs d'une action enregistrée sans garde sont donc invisibles dans le journal. | [Code] |
| C7 | **`os.startfile("spotify:")`** (`actions_spotify.py:68`) ouvre Spotify en pleine partie : vol de focus possible, contraire à un anti-objectif de la spec. | [Code], effet [NV] |
| C8 | **discord.py importe `audioop`**, retiré de Python 3.13. Le projet est bloqué en 3.12 tant que ce n'est pas réglé. | [Exécuté] |
| C9 | **La conception Claude repose sur la connexion claude.ai de l'utilisateur** et retire de force `ANTHROPIC_API_KEY` (`claude_session.py:50`). Pour une application tierce distribuée, c'est contraire aux conditions d'Anthropic, sauf approbation (section 5.3). | [Code] + [Source] |
| C10 | **Le Client ID Spotify est fourni par chaque utilisateur** et l'application est en mode développement. Un Client ID partagé serait plafonné à 5 utilisateurs (section 5.1). | [Code] + [Source] |

### 3.3 Ce qui manque pour un produit

- **L'installation.** Il n'y a ni installateur, ni exécutable, ni signature de code. Le parcours actuel est `git clone`, puis `uv sync`, puis le téléchargement manuel de la voix Piper. Le modèle Whisper est téléchargé au premier lancement, sans contrôle d'intégrité.
- **La configuration.** Il n'y a pas d'interface de réglages, d'assistant de premier lancement ni d'icône de zone de notification. Tout se règle en éditant le TOML, y compris des identifiants Discord à copier en mode développeur.
- **Le micro.** On ne peut pas choisir le micro (périphérique par défaut uniquement). Il n'y a ni test de niveau, ni réduction de bruit, ni annulation d'écho.
- **L'interface sans deuxième écran.** Si `second_screen_index` n'existe pas, la fenêtre reste masquée (`screen.py`, `select_monitor`). Avec un seul écran, les demandes d'autorisation de Claude sont **invisibles**.
- **Les mises à jour, le support et la diagnostic.** Il n'y a pas de mise à jour automatique, pas de migration de configuration, pas d'export de diagnostic et pas de rapport de plantage.
- **L'extension.** Pour ajouter une commande, il faut modifier `ACTION_NAMES` (`actions.py`), écrire une regex dans `intent.py` et le câblage dans `__main__.py`. Il n'y a pas d'API de plugin.
- **La langue.** Seul le français est géré : `language="fr"` est codé en dur (`audio/stt.py:46`), et la grammaire est française.
- **L'intégration continue.** Il n'y a ni CI, ni linter, ni vérification de types.
- **Le cadre légal.** Il n'y a ni licence du projet, ni inventaire des licences des modèles (voix Piper, openWakeWord, Whisper), ni politique de confidentialité.

## 4. Tout ce qui suppose un utilisateur unique, et comment le lever

| # | Où | Hypothèse | Comment la lever | Lot |
|---|---|---|---|---|
| U1 | `README.md:3`, `README.md:23` ; spec ligne 3 ; spec « Non-objectifs » ligne 23 ; plan « Global Constraints » | « Usage personnel, un seul utilisateur » est un non-objectif explicite. | Réécrire l'intention : « tout joueur PC Windows ». Déplacer le multi-utilisateur des non-objectifs vers les objectifs. Garder l'historique de décision dans un ADR. | L18 |
| U2 | Spec, ligne 40 | Les choix techniques sont calibrés sur une machine précise (Ryzen 7 5700, RTX 4060, 16 Go). | Définir une configuration minimale et une configuration recommandée. Choisir le modèle de transcription et l'appareil automatiquement selon le matériel détecté. Mesurer sur 3 profils de machine. | L9, L5 |
| U3 | Spec, ligne 43 (« Casque ») | Pas d'annulation d'écho, parce que l'utilisateur joue au casque. | Beaucoup de joueurs jouent sur haut-parleurs. Il faut une annulation d'écho (AEC) et une réduction de bruit, ou au minimum détecter la sortie haut-parleurs et prévenir l'utilisateur. Sur haut-parleurs, la voix d'un ami sur Discord peut dire « oui docteur » (voir L1). | L11 |
| U4 | Spec, ligne 44 ; `claude_session.py:50` | Abonnement Claude Pro de l'utilisateur, connexion claude.ai, clé API interdite. | Inverser : clé API fournie par l'utilisateur (BYOK), stockée de façon chiffrée. Pas de login claude.ai sans approbation d'Anthropic. Fonction facultative. | L1 |
| U5 | `actions_discord.py` ; `config.py` (`owner_id`) ; README, section Discord | Chaque utilisateur crée son propre bot, l'invite sur ses serveurs avec les droits Mute et Move Members (donc il faut être administrateur) et copie des identifiants en mode développeur. | Ce parcours est irréaliste pour le grand public. Il faut le sortir du parcours par défaut (voir L4) et ne le garder qu'en option « avancé, administrateurs de serveur ». | L4 |
| U6 | `actions_spotify.py` ; README, section Spotify | Chaque utilisateur crée une application développeur Spotify et a un compte Premium. | Les contrôles de base passent par SMTC, sans compte. La Web API devient une option avancée, avec le Client ID de l'utilisateur (section 5.1). | L3 |
| U7 | README, section « Entraîner le mot de réveil » ; `tools/train_wake.py` | Le mot de réveil est entraîné sur la voix d'une personne (80 prises, 55 min de calcul). | Il faut un modèle indépendant du locuteur, livré prêt, avec au plus un calibrage de seuil. | L10 |
| U8 | `__main__.py:15` (`ROOT`) ; `__main__.py:146` (`.spotify-cache`) ; `_rooted` | Configuration, secrets, cache de jeton et modèles sont dans le dossier du dépôt. | Utiliser `%APPDATA%\DrVocal` pour la configuration, `%LOCALAPPDATA%\DrVocal` pour les modèles et le cache, et le Gestionnaire d'identification Windows (DPAPI) pour les secrets. | L2 |
| U9 | `config.example.toml:40` | Un projet par défaut pointe vers `D:/NasaCode/DrVocal`. | Pas de projet par défaut ; ajout par sélecteur de dossier dans l'interface. | L8 |
| U10 | `config.example.toml:36` ; `screen.py` | Un deuxième écran est supposé (index 1 par défaut). | Détecter le nombre d'écrans. Avec un seul écran, utiliser des notifications Windows ou un petit indicateur discret, et une file d'attente consultable après la partie. | L19 |
| U11 | `audio/stt.py:46` ; `intent.py` ; `claude_policy.py` (`parse_reply`) | Français uniquement. | Rendre la langue configurable (transcription et grammaire par langue), le français d'abord, l'anglais ensuite. | L20 |
| U12 | `docs/mesures.md` ; `audio/wake.py` ; constantes de `actions_spotify.py` | Les seuils sont réglés sur le micro Realtek de l'utilisateur (patience 2, seuil 0,9) et sur sa bibliothèque (« Daryana », « Mc Pao »). | Valider les seuils sur un corpus multi-locuteurs, multi-micros et multi-bibliothèques. Calibrer le niveau du micro au premier lancement. | L10, L13 |
| U13 | `docs/anti-triche.md` ; spec, « Intention » | L'analyse anti-cheat porte sur les 5 jeux de l'utilisateur. | Écrire une politique générale qui ne dépend pas du jeu : aucune injection vers le jeu (voir L4 et L14). | L14 |
| U14 | `config.py:71` | Les notes vont dans `~/Documents/NOTES`, ce qui ignore la redirection OneDrive et les noms localisés. | Utiliser `SHGetKnownFolderPath(FOLDERID_Documents)`. | L2 |
| U15 | `tools/install_autostart.py` | Le démarrage automatique pointe vers `.venv\Scripts\pythonw.exe` du dépôt. | Le confier à l'installateur, avec désinstallation propre. | L7 |
| U16 | `app.py` (`Timings`) | Les délais sont codés en dur et réglés pour un seul débit de parole. | Les exposer dans les réglages avancés et les adapter (par exemple, silence de fin selon le débit mesuré). | L11 |
| U17 | Spotify, quotas | Une seule bibliothèque, rechargée toutes les heures (`LIBRARY_TTL`). Avec un Client ID partagé, les limites de débit seraient communes à tous les utilisateurs. | Le Client ID par utilisateur règle la question. Garder un recul (backoff) sur les erreurs 429. | L3 |

## 5. API tierces : conditions vérifiées et conséquences pour l'architecture

Toutes ces informations ont été vérifiées le 2026-11-05 dans des sources officielles, sauf mention [NV].

### 5.1 Spotify

**Mode développement**

- **[Source]** Au plus 5 utilisateurs authentifiés.
- Le propriétaire de l'application doit être Premium.
- Ces règles valent pour les nouveaux Client ID depuis le 2026-02-11, et pour les intégrations existantes depuis le 2026-03-09.
- Le mode développement est réservé aux projets personnels non commerciaux.
- Sources :
  - https://developer.spotify.com/documentation/web-api/concepts/quota-modes
  - https://developer.spotify.com/blog/2026-02-06-update-on-developer-access-and-platform-security

**Accès étendu (Extended quota)**

- **[Source]** Depuis le 2025-05-15, il est réservé aux organisations enregistrées, avec un service lancé et **au moins 250 000 utilisateurs actifs mensuels**.
- Source : https://developer.spotify.com/blog/2025-04-15-updating-the-criteria-for-web-api-extended-access

**API Player**

- **[Source]** Elle exige Premium.
- Source : https://developer.spotify.com/documentation/web-api/reference/start-a-users-playback

**Authentification**

- **[Source]** PKCE est le flux recommandé pour une application de bureau.
- Source : https://developer.spotify.com/documentation/web-api/tutorials/code-pkce-flow

**Changements de février 2026 (mode développement)**

- **[Source]** La recherche est limitée à 10 résultats, ce qui est déjà pris en compte (`SEARCH_LIMIT`).
- `/me/tracks` devient `/me/library`. **[NV]** Je n'ai pas vérifié si spotipy 2.26 appelle encore `/me/tracks` pour `current_user_saved_tracks`. Le code avale l'erreur sans bruit : « titres likés indisponibles ».
- Source : https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide

**Conditions des développeurs (Developer Terms v10)**

- **[Source]** Usage privé et personnel pour les applications de streaming, ce qui inclut le contrôle de lecture.
- Code de sécurité propre à chaque application, à ne pas divulguer.
- Aucune interdiction explicite des assistants vocaux.
- Source : https://developer.spotify.com/terms

**Chaque utilisateur avec sa propre application**

- **[NV]** Les conditions ne l'interdisent pas explicitement. C'est une zone grise, mais c'est cohérent avec « usage personnel » si chacun utilise sa propre application.

**Conséquences pour l'architecture**

- Une application gratuite publiée par un particulier **ne peut pas** obtenir l'accès étendu.
- Un Client ID unique intégré au produit est donc exclu (5 utilisateurs au plus).
- Par défaut, il faut utiliser **SMTC de Windows** : `GlobalSystemMediaTransportControlsSessionManager` permet lecture, pause, suivant et précédent, fonctionne avec Spotify Free, sans compte et sans injection de touches. **[Source]** https://learn.microsoft.com/en-us/uwp/api/windows.media.control.globalsystemmediatransportcontrolssessionmanager
- Le volume peut passer par le volume de la session audio de Spotify (Core Audio).
- La fonction « lancer un artiste ou une playlist par son nom » devient une **option avancée** :
  - l'utilisateur fournit son propre Client ID, guidé pas à pas par l'interface, et doit être Premium ;
  - l'interface l'explique honnêtement.

### 5.2 Discord

**RPC local**

- **[Source]** Sans approbation de Discord : 50 testeurs au plus.
- `SET_VOICE_SETTINGS` permet de couper le micro et le son.
- Le transport WebSocket est déprécié.
- Discord oriente vers le Social SDK.
- Source : https://docs.discord.com/developers/topics/rpc

**Approbation du scope vocal**

- **[NV]** Je n'ai trouvé aucun processus public pour obtenir l'approbation de `rpc.voice.write`.

**Game SDK**

- **[Source]** Il est obsolète, et sa partie Voice est arrêtée depuis le 2023-05-02.
- Source : https://support-dev.discord.com/hc/en-us/articles/30125671534359

**Social SDK**

- **[Source]** Les réglages vocaux du client sont en **lecture seule**. Il ne peut pas couper le micro dans un salon Discord normal.
- Source : https://docs.discord.com/developers/discord-social-sdk/development-guides/managing-voice-chat

**Selfbots**

- **[Source]** Ils sont interdits.
- Source : https://support.discord.com/hc/en-us/articles/115002192352

**Conséquences pour l'architecture**

- Aucune voie officielle ne permet, à grande échelle, de couper le micro Discord d'un utilisateur quelconque depuis une application tierce.
- Le bot actuel ne coupe pas vraiment le micro : il applique un **mute serveur**. Il faut :
  - être administrateur ;
  - inviter le bot ;
  - être déjà dans un salon.

  À grande échelle, un bot partagé exigerait aussi un hébergement 24 h/24, une vérification au-delà de 100 serveurs et une justification de l'intent privilégié Server Members. **[NV]** Ces règles de vérification n'ont pas été relues dans cette revue.
- Options, par ordre de préférence :
  1. **Couper le micro au niveau Windows.** `IAudioEndpointVolume::SetMute` sur le périphérique de capture n'injecte rien et fonctionne avec toutes les applications de chat.
     - Inconvénient : Dr Vocal n'entend plus rien non plus.
     - « Réactive mon micro » doit donc passer par la touche (appui long ou geste dédié) ou par une capture parallèle. **[NV]** Le comportement exact de la coupure d'un endpoint vis-à-vis des autres clients de capture est à prototyper.
  2. **Raccourcis Discord simulés** (SendInput), en option, désactivés par défaut et avec un avertissement. Ils ne s'activent jamais si un processus de jeu protégé par un anti-cheat connu est au premier plan.
  3. **Bot**, en option pour les administrateurs de serveur : message, déplacement, mute d'un membre.
  4. **RPC**, seulement si Discord approuve l'application. Prise de contact à lancer en parallèle (P3).

### 5.3 Claude (Agent SDK, Claude Code)

**Connexion**

- **[Source]** Sauf approbation préalable, Anthropic ne permet pas aux développeurs tiers d'offrir la connexion claude.ai ni ses limites d'usage, y compris pour les agents bâtis sur l'Agent SDK. Il faut une clé API.
- Source : https://code.claude.com/docs/en/agent-sdk/overview

**Marque**

- **[Source]** « Claude Code » est interdit comme nom de produit ou de fonction, de même qu'un visuel qui imite Claude Code. Sont permis : « Claude Agent » ou « {Nom} Powered by Claude ».
- Les termes commerciaux s'appliquent : https://www.anthropic.com/legal/commercial-terms

**Modes de permission**

- **[Source]** `bypassPermissions` n'est fait que pour des conteneurs ou des VM isolés.
- Pour l'automatisation, la doc conseille `dontAsk` avec `--allowedTools`.
- Le sandbox Bash n'existe **pas en Windows natif**.
- Source : https://code.claude.com/docs/en/permission-modes

**Appel du CLI déjà connecté de l'utilisateur**

- **[NV]** Le cas où Dr Vocal appelle le CLI `claude` de l'utilisateur, déjà connecté, n'est pas explicitement traité par la doc. À confirmer auprès d'Anthropic avant d'en faire un mode pris en charge.

**Conséquences pour l'architecture**

- La fonction Claude devient facultative, désactivée par défaut, avec la **clé API de l'utilisateur** stockée dans le Gestionnaire d'identification.
- Il faut supprimer `scrub_environ` et l'interdiction de clé (C9).
- Il faut renommer tout ce qui apparaît à l'utilisateur (« sessions Claude Code » devient « Claude Agent » ou « Powered by Claude »).
- Le mode actuel (`default`, avec un hook qui décide) reste acceptable. Évaluer `dontAsk` avec une liste blanche, qui refuse par construction ce qui n'est pas prévu.

### 5.4 Anti-cheats

**Riot (Vanguard)**

- **[Source]** Les scripts et auto-clickers peuvent mener à un bannissement permanent. Il n'y a pas de liste blanche.
- Depuis le 2026-10-06, l'accès mémoire est bloqué pour les applications tierces inconnues.
- Sources :
  - https://www.riotgames.com/en/DevRel/vanguard-faq
  - https://support.riotgames.com/en-us/riot/performance/game-memory-access-removed-for-third-party-apps

**FACEIT**

- **[Source]** Les macros et scripts non autorisés sont interdits. Un logiciel non listé peut déclencher un avertissement.
- Source : https://support.faceit.com/hc/en-us/articles/360015788779

**BattlEye**

- **[Source]** Les outils de macro peuvent valoir une expulsion de partie. Les overlays sont tolérés.
- Source : https://www.battleye.com/support/faq/

**Easy Anti-Cheat et SendInput**

- **[NV]** Je n'ai trouvé aucune politique publique d'EAC pour les joueurs.
- **[NV]** Aucune source officielle ne cite SendInput nommément.

**Valve (CS2)**

- **[Doc]** « Never use any automation for any reason. » (`docs/anti-triche.md`)

**Conséquences pour l'architecture**

- Ne jamais envoyer de touche vers un jeu.
- Pas d'injection de DLL, pas de hook dans le processus du jeu, pas de lecture de sa mémoire.
- Pas d'overlay injecté : rester une fenêtre séparée ou une notification système.
- Préférer SMTC et Core Audio à toute touche simulée.
- Signer le binaire, pour limiter aussi les faux positifs des antivirus.

## 6. Architecture cible (vue d'ensemble)

```
Interface (icône de notification, réglages, assistant de premier lancement, notifications)
        │  IPC local (ou même processus)
Moteur audio : micro choisi → réduction de bruit / AEC → réveil (touche | mot) → VAD → STT (auto CPU/GPU)
        │  texte
Compréhension : grammaires déclarées par chaque extension (+ synonymes), multilingue
        │  Intent
Catalogue fermé : extensions installées explicitement, chacune déclare son niveau de risque
        │
Fournisseurs : Médias (SMTC → Web API facultative) · Voix/Chat (coupure Windows → raccourcis facultatifs → bot facultatif)
               · Notes · Claude Agent (clé API utilisateur, facultatif)
Transversal : stockage %APPDATA% + secrets DPAPI · journal + export de diagnostic · mise à jour signée
```

Principes à inscrire dans la nouvelle spec :

- tout fonctionne sans aucun compte tiers ;
- chaque intégration est facultative et se connecte depuis l'interface ;
- le défaut est toujours l'option sans risque anti-cheat ;
- aucune donnée ne sort du PC avant le réveil.

## 7. Chantiers (lots indépendants)

Récapitulatif :

| Lot | Titre | Priorité | Effort | Dépend de | Conflit de fichiers avec |
|---|---|---|---|---|---|
| L1 | Claude : conformité et sécurité | P0 | M | aucun | aucun |
| L2 | Stockage, secrets et chemins hors du dépôt | P0 | M | aucun | L3 (`__main__.py`) |
| L3 | Médias sans compte (SMTC) et Spotify facultatif | P0 | M | aucun | L2, L7 |
| L4 | Voix et chat sans bot ni injection | P0 | M | aucun | L14 |
| L5 | Banc de mesure en jeu et instrumentation | P0 | M | aucun | aucun |
| L6 | Licences et confidentialité | P0 | S | aucun | aucun |
| L7 | Exécutable, installateur et signature | P0 | L | L2 | aucun |
| L8 | Assistant de premier lancement et réglages | P0 | L | L2 | aucun |
| L9 | Transcription : latence et précision | P1 | M | L5 (mesure) | aucun |
| L10 | Mot de réveil universel et faux réveils | P1 | XL | L5 | aucun |
| L11 | Robustesse audio (micro, bruit, écho) | P1 | M | aucun | aucun |
| L12 | API d'extension (plugins) | P1 | L | aucun | L13 (à faire après) |
| L13 | Compréhension : corpus réel et grammaire déclarative | P1 | M | L12 | L12 |
| L14 | Garde-fous anti-cheat et sobriété en jeu | P1 | M | aucun | L4 |
| L15 | Diagnostic et support | P1 | M | L2 | aucun |
| L16 | Qualité : CI, lint, fins de ligne, Python 3.13 | P1 | S | aucun | aucun |
| L17 | Mises à jour automatiques | P1 | M | L7 | aucun |
| L18 | Documentation et spec multi-utilisateurs | P1 | S | décisions de la section 8 | aucun |
| L19 | Fonctionnement avec un seul écran | P1 | M | aucun | aucun |
| L20 | Anglais et multilingue | P2 | L | L13 | aucun |
| L21 | Profils par jeu | P2 | M | L14 | aucun |
| L22 | Commandes cachées aux amis (micro virtuel) | P3 | XL | L4 | aucun |
| L23 | Approbations Claude depuis le téléphone | P3 | L | L1, L19 | aucun |

---

### L1 Claude : conformité et sécurité (P0, M)

**Objectif.** Rendre la fonction Claude légale pour une application distribuée et sûre face aux erreurs de transcription et à l'injection de prompt.

**Justification.**

- C9 et la section 5.3 : la connexion claude.ai n'est pas permise à un tiers.
- La validation vocale d'une commande shell lue par synthèse en pleine partie n'est pas un consentement éclairé. Le résumé dit « Bash : command = … », jusqu'à 200 caractères (`claude_session.py:264`).
- Sur haut-parleurs, un tiers ou un ami sur Discord peut dire « oui docteur ».

**Fichiers.** `src/drvocal/claude_session.py`, `src/drvocal/claude_policy.py`, `src/drvocal/app.py` (`register_claude`, `make_ask_user`), les tests associés.

**Tâches.**

1. **Clé API.**
   - Supprimer `_FORBIDDEN_ENV`, `scrub_environ` et `build_env`.
   - Lire une clé API depuis le magasin de secrets (interface fournie par L2 ; d'ici là, une fonction injectée).
   - Sans clé, ne pas enregistrer `claude.prompt` ni `claude.continue`.
2. **Approbation vocale limitée.** Elle ne vaut plus que pour une liste courte de catégories à faible risque (par exemple `WebSearch`, la lecture hors projet). Les commandes `Bash` et `PowerShell` et les écritures sensibles vont **toujours** dans la file d'attente à l'écran.
3. **Dossiers de projet.** Refuser une racine de lecteur, le dossier personnel, `%APPDATA%` et `C:\Windows`. Exiger un dossier qui existe.
4. **Fichiers qui finissent par être exécutés.** Les traiter comme une configuration d'exécution, donc ASK : `package.json`, `pyproject.toml`, `Makefile`, `*.ps1`, `*.bat`, `*.cmd`, `conftest.py`, `CLAUDE.md`, `.github/**` (déjà caché), `*.csproj`, `setup.py`, etc.
5. **Limites de session.** `max_turns`, un budget (`max_budget_usd`, si l'option existe dans la version du SDK utilisée : **[NV]**, à vérifier) et une durée maximale.
6. **Arrêt à la voix.** Une commande « arrête Claude » qui interrompt la session en cours.
7. **Journal d'audit.** Un fichier JSONL des outils autorisés, refusés et approuvés, sans contenu de fichier.
8. **Marque.** Renommer tout texte visible par l'utilisateur en « Claude Agent » ou « Powered by Claude ».
9. **Mode de permission.** Évaluer `permission_mode="dontAsk"` avec `allowed_tools` contre le hook actuel. Garder le hook, qui échoue en mode fermé, si `dontAsk` ne permet pas la file d'attente.

**Critères de réussite.**

- Aucun chemin de code n'utilise de jeton claude.ai. Un test vérifie que la clé passée vient du magasin de secrets.
- Un test montre qu'une commande `Bash` n'est **jamais** soumise à une approbation vocale.
- Des tests montrent que les dossiers de projet `C:/` et `~` sont refusés.
- Des tests montrent que l'écriture dans `package.json` et dans `CLAUDE.md` passe en ASK.
- « Arrête Claude » interrompt une session simulée en moins de 2 s.
- La recherche de « Claude Code » dans les textes destinés à l'utilisateur (README, interface) ne renvoie rien.

**Hors périmètre.** Interface de saisie de la clé (L8). Téléphone (L23).

---

### L2 Stockage, secrets et chemins hors du dépôt (P0, M)

**Objectif.** Le programme installé ne dépend plus du dossier du dépôt, et aucun secret n'est stocké en clair.

**Justification.**

- U8 et U14.
- `.spotify-cache` (jeton de rafraîchissement Spotify) est en clair à la racine.
- `secrets.toml` est en clair.
- `ROOT = Path(__file__).parent.parent.parent` (`__main__.py:15`) casse une fois le paquet installé ailleurs que dans le dépôt.

**Fichiers.** `src/drvocal/config.py`, `src/drvocal/__main__.py`, nouveau `src/drvocal/storage.py`, `tools/spotify_login.py`, tests.

**Tâches.**

1. **Module `storage.py`.**
   - `config_dir()` renvoie `%APPDATA%\DrVocal`.
   - `data_dir()` renvoie `%LOCALAPPDATA%\DrVocal` (modèles, cache, journaux).
   - `documents_dir()` utilise `SHGetKnownFolderPath`.
2. **Secrets.** Créer `SecretStore` sur le Gestionnaire d'identification Windows, via `keyring` ou DPAPI avec `CryptProtectData`. Il couvre la clé Claude, le jeton Spotify et le jeton du bot Discord.
3. **Jeton Spotify.** Remplacer `CacheFileHandler` par un `CacheHandler` adossé à `SecretStore`.
4. **Migration au premier lancement.** Si `config.toml`, `secrets.toml` ou `.spotify-cache` existent à l'ancien emplacement, les importer, chiffrer les secrets, puis renommer les anciens fichiers en `.migrated`.
5. **Configuration versionnée.** Ajouter un champ `schema_version` à la configuration et une fonction de migration.
6. **Chemins relatifs.** `_rooted` se résout depuis `data_dir()` pour les modèles.

**Critères de réussite.**

- Après migration, le dépôt et `%APPDATA%` ne contiennent aucun secret en clair. Un test le vérifie par recherche des valeurs.
- Le programme démarre depuis un paquet installé dans un dossier quelconque. Un test lance `python -m drvocal --check` depuis un `tmp_path`, avec ce nouveau drapeau de vérification.
- Les notes vont dans le dossier Documents réel, OneDrive compris.

---

### L3 Médias sans compte (SMTC) et Spotify facultatif (P0, M)

**Objectif.** « Pause », « suivant », « précédent », « reprends » et « volume » fonctionnent pour tout utilisateur, avec Spotify Free ou n'importe quel lecteur, sans compte ni configuration.

**Justification.** U6, C10 et section 5.1. C7 : ouvrir Spotify en pleine partie.

**Fichiers.** Nouveau `src/drvocal/actions_media.py`, `src/drvocal/actions_spotify.py`, `src/drvocal/actions.py` (noms d'action), `src/drvocal/__main__.py` (enregistrement), tests.

**Tâches.**

1. **Actions `media.*` sur SMTC.** Utiliser `winrt-Windows.Media.Control`, ou `winsdk` selon le paquet maintenu : **[NV]**, à choisir. Couvrir `pause`, `resume`, `next`, `previous`, avec choix de la session Spotify si elle existe, sinon de la session active.
2. **Volume.** Utiliser le volume de la session audio du lecteur (Core Audio, `ISimpleAudioVolume`, via `pycaw` : **[NV]**).
3. **Choix du fournisseur.** Les intents `spotify.pause/next/previous/resume/volume` deviennent `media.*`. Le fournisseur est choisi dans cet ordre : Web API si elle est connectée, sinon SMTC.
4. **`spotify.play` (par nom).** Ne s'enregistre que si un Client ID utilisateur est connecté.
5. **Ouverture de Spotify.** Ne plus l'ouvrir automatiquement quand un jeu est au premier plan, en s'appuyant sur la détection fournie par L14 ou sur une fonction injectée. Sinon, l'ouvrir minimisé (`SW_SHOWMINNOACTIVE` via `ShellExecute`), et vérifier que le focus n'a pas changé.
6. **Erreurs 429.** Les gérer avec recul exponentiel. Journaliser l'endpoint en échec quand la bibliothèque échoue (`/me/tracks` contre `/me/library`, section 5.1).

**Critères de réussite.**

- Sur un PC sans aucun secret, « pause » et « suivant » agissent sur Spotify Free et sur un autre lecteur (navigateur YouTube). C'est un test manuel, avec un test automatique sur une fausse API SMTC.
- Aucun appel `SendInput` n'est fait.
- Test manuel : avec un jeu en plein écran au premier plan, « mets Daft Punk » ne change pas la fenêtre active. Vérifier `GetForegroundWindow` avant et après.

---

### L4 Voix et chat sans bot ni injection (P0, M)

**Objectif.** « Coupe mon micro » et « mets-moi en sourdine » marchent pour tout joueur, sans bot, sans être administrateur et sans risque anti-cheat.

**Justification.** U5 et section 5.2.

**Fichiers.** Nouveau `src/drvocal/actions_voice.py`, `src/drvocal/actions_discord.py` (devient facultatif), `src/drvocal/actions_hotkeys.py`, `src/drvocal/__main__.py`, tests.

**Tâches.**

1. **Prototype de coupure Windows.** Couper le micro avec `IAudioEndpointVolume::SetMute` sur le périphérique de capture choisi. Mesurer :
   - si Discord reçoit du silence (oui ou non) ;
   - si Dr Vocal reçoit encore du signal (oui ou non).

   Conclure par écrit dans `docs/`.
2. **Réactivation.** Si Dr Vocal n'entend plus rien micro coupé, prévoir la réactivation par un geste sur la touche, par exemple un appui long de 1 s ou un double appui, toujours en lecture passive. Un son confirme l'état.
3. **Sourdine.** Couper la session audio de sortie de Discord (Core Audio par processus `Discord.exe`) : le joueur n'entend plus Discord, sans injection.
4. **Raccourcis simulés.** Garder `actions_hotkeys` en option. Ajouter un blocage si le processus au premier plan est un jeu connu (liste dans L14).
5. **Bot.** Le marquer « avancé, administrateurs », hors du parcours par défaut, et supprimer l'exigence de copier `owner_id` à la main. L'identifiant est récupéré par OAuth2 `identify` : **[NV]**, à concevoir.

**Critères de réussite.**

- Sur un PC sans bot et sans raccourci, « coupe mon micro » fait entendre du silence aux amis dans un appel Discord de test, et l'action inverse le rétablit.
- Aucun `SendInput` n'est fait dans ce parcours (test).
- Un document de décision explique le mécanisme retenu, ses limites, et indique si Dr Vocal entend encore quand le micro est coupé.

---

### L5 Banc de mesure en jeu et instrumentation (P0, M)

**Objectif.** Remplacer les promesses par des chiffres reproductibles : FPS, processeur, RAM, latence et faux réveils.

**Justification.** C3. Sans mesure, les objectifs « ne pèse rien » et « réagit instantanément » ne sont pas vérifiables.

**Fichiers.** `src/drvocal/app.py` (horodatages), nouveau `tools/bench_game.py`, `tools/measure_idle.py`, `docs/mesures.md`.

**Tâches.**

1. **Horodatages.** Les ajouter dans `Assistant` : `t_wake`, `t_speech_end`, `t_transcribed`, `t_intent`, `t_action_done`. Les journaliser en INFO, sans le texte.
2. **`tools/bench_game.py`.** Il lance PresentMon (licence MIT, Intel) en ligne de commande pour capturer les temps d'image du jeu, avec et sans Dr Vocal. Il injecte une commande WAV toutes les N secondes par un faux micro, et produit un rapport : FPS moyen, 1 % low, delta, latence p50 et p95 des commandes.
3. **Corpus de faux réveils.** Lire au moins 3 h d'audio de jeu et de discussion (enregistrements consentis, ou corpus public de parole française plus bruit de jeu) en mode `voice`, et compter les réveils.
4. **Protocole.** Fixer 3 profils de machine (entrée, milieu et haut de gamme) et 3 jeux (un compétitif CPU-bound, un AAA GPU-bound, un léger). Remplir `docs/mesures.md`.

**Critères de réussite.**

- Un rapport par profil et par jeu est publié dans `docs/mesures.md`.
- Seuils d'acceptation pour la suite :
  - delta de FPS moyen inférieur à 1 % en veille et à 3 % pendant une transcription ;
  - 1 % low dégradé de moins de 5 % ;
  - latence p95 de la fin de phrase à l'action inférieure à 1 s pour les commandes médias.

---

### L6 Licences et confidentialité (P0, S)

**Objectif.** Pouvoir distribuer légalement.

**Justification.** Il n'y a pas de `LICENSE`. Les modèles livrés ont des licences variables. **[NV]** Je n'ai pas vérifié les licences des voix Piper `fr_FR-*`, des modèles openWakeWord et de faster-whisper/CTranslate2 : certaines voix ou certains modèles pré-entraînés pourraient être non commerciaux.

**Fichiers.** `LICENSE`, `THIRD_PARTY_NOTICES.md`, `docs/confidentialite.md`.

**Tâches.**

1. Choisir la licence du projet. C'est une décision de l'auteur (section 8).
2. Inventorier chaque dépendance et chaque modèle livré : licence, attribution exigée, usage commercial permis ou non. Écarter ce qui n'est pas compatible.
3. Rédiger une politique de confidentialité :
   - pas d'audio avant le réveil ;
   - rien ne quitte le PC sauf les appels Spotify, Discord et Claude explicitement activés ;
   - télémétrie seulement si l'utilisateur l'active, sans audio ni transcription.

**Critères de réussite.**

- Chaque fichier livré par l'installateur figure dans `THIRD_PARTY_NOTICES.md` avec sa licence.
- Aucun composant non commercial n'est livré si la licence choisie l'interdit.

---

### L7 Exécutable, installateur et signature (P0, L) (dépend de L2)

**Objectif.** Le joueur télécharge un `.exe`, clique « Suivant », et Dr Vocal tourne, sans Python, sans uv et sans ligne de commande.

**Justification.** Section 3.3. U15.

**Fichiers.** Nouveau dossier `packaging/`, fichier de build, `tools/install_autostart.py` (supprimé ou remplacé).

**Tâches.**

1. **Geler l'application.** Utiliser PyInstaller ou Nuitka, avec onnxruntime, ctranslate2, sounddevice/PortAudio et pywebview/WebView2. Vérifier l'absence de console (`pythonw`).
2. **Installateur par utilisateur, sans droits administrateur.** Utiliser Inno Setup, ou Velopack si on veut mutualiser avec L17. Il gère le démarrage automatique (clé `Run`), le raccourci du menu Démarrer et une désinstallation qui retire la clé `Run`, avec option de suppression des données.
3. **Modèles.**
   - Inclure le modèle de transcription par défaut et la voix, ou les télécharger au premier lancement avec une **somme SHA-256 attendue** et une barre de progression.
   - Interdire le téléchargement implicite de faster-whisper depuis Hugging Face au moment d'une commande.
4. **Signature.** Signer l'exécutable et l'installateur (certificat de signature de code, ou Azure Trusted Signing) pour limiter SmartScreen et les faux positifs antivirus.
5. **Vérification VirusTotal.** Lancer une vérification à chaque version.

**Critères de réussite.**

- Sur une VM Windows 11 vierge, l'installation, le premier lancement et une commande « pause » qui réussit prennent **moins de 5 minutes**, connexion comprise.
- La désinstallation ne laisse ni clé `Run` ni processus.
- 0 détection VirusTotal sur les moteurs majeurs, ou un faux positif documenté et signalé.

---

### L8 Assistant de premier lancement et réglages (P0, L) (dépend de L2)

**Objectif.** Configurer Dr Vocal sans fichier : choix du micro, touche, test de reconnaissance, intégrations facultatives.

**Justification.** U9 et section 3.3.

**Fichiers.** Nouveau `src/drvocal/ui/` (pywebview est déjà présent ; une seule fenêtre sert aux réglages et à l'assistant), `src/drvocal/__main__.py`, `src/drvocal/config.py` (écriture de la configuration).

**Tâches.**

1. **Icône de notification** (par exemple `pystray`) : état (veille, écoute, coupé), Réglages, Pause de l'écoute, Quitter.
2. **Assistant de premier lancement.**
   1. Choix du micro, avec un vumètre et un avertissement si le niveau est trop faible.
   2. Choix de la touche par capture : « appuie sur la touche que tu veux », en lecture passive. Avertissement si c'est une touche courante de jeu (Z, Q, S, D, W, A, espace, etc.).
   3. Test : « dis "pause" », avec la transcription affichée.
   4. Intégrations facultatives :
      - Spotify avancé : guide pour créer son Client ID, puis OAuth PKCE ;
      - Claude : saisie de la clé API, testée ;
      - Discord bot : avancé.
3. **Page Réglages.** Elle couvre tout `Settings` et écrit la configuration de façon atomique. Un champ invalide est refusé dans l'interface, pas au démarrage.
4. **Projets Claude.** Ajout par sélecteur de dossier, avec les règles de L1.
5. **Synonymes.** Éditeur de « phrase dite → commande ».

**Critères de réussite.**

- Test utilisateur avec 5 joueurs qui n'ont jamais vu le projet : 5 sur 5 terminent l'assistant sans aide, en moins de 3 minutes en médiane.
- Aucune étape n'exige d'ouvrir un fichier ou un terminal.

---

### L9 Transcription : latence et précision (P1, M) (après L5 pour mesurer)

**Objectif.** Latence p95 de la fin de phrase à l'action inférieure à 1 s sur la configuration recommandée, et précision mesurée sur de vraies voix.

**Justification.** C2. Le modèle `small` sur processeur est mesuré à 1,43 s. U2.

**Fichiers.** `src/drvocal/audio/stt.py`, `tools/bench_stt.py`, tests.

**Tâches.**

1. **Choix automatique.**
   - Carte NVIDIA avec plus de 6 Go libres et CUDA disponible : `large-v3-turbo` en `int8_float16` sur la carte.
   - Sinon : `small` sur le processeur.

   Livrer les DLL cuBLAS et cuDNN nécessaires, ou les télécharger à la demande (C2).
2. **Threads.** Fixer `cpu_threads` (2 ou 4) pour ne pas saturer les cœurs du jeu. Aujourd'hui, c'est la valeur par défaut de CTranslate2 (4 selon la docstring de faster-whisper).
3. **Biais de vocabulaire.** Utiliser `hotwords` ou `initial_prompt`, avec les verbes de commande et les noms de la bibliothèque, des projets et des salons (faster-whisper 1.2.1 expose `hotwords` : vérifié dans le paquet installé). Mesurer le gain sur les noms d'artistes.
4. **Commandes courtes.** Évaluer `beam_size=1` contre `beam_size=5`, et `without_timestamps=True`.
5. **Corpus de test.** Au moins 300 énoncés réels, au moins 20 locuteurs, avec bruit de jeu ajouté à 0, 10 et 20 dB de rapport signal/bruit. Le versionner hors dépôt avec consentement.

**Critères de réussite.**

- p95 inférieur à 1 s sur la configuration recommandée et inférieur à 1,8 s sur la configuration minimale. Ces chiffres sont mesurés par L5.
- Taux de commandes exactes (intent juste) supérieur ou égal à 95 % à 10 dB.

---

### L10 Mot de réveil universel et faux réveils (P1, XL)

**Objectif.** Un mot de réveil qui marche pour tout le monde sans entraînement, avec moins d'un faux réveil par heure de discussion.

**Justification.** C1 et U7. Le modèle actuel ne généralise pas : 6/12, et il réagit au souffle du micro.

**Fichiers.** `src/drvocal/audio/wake.py`, `tools/train_wake.py`, `tools/eval_voice.py`, nouveau corpus.

**Tâches.**

1. **Décision de moteur.** Comparer sur le même protocole :
   - openWakeWord avec un entraînement massif (des centaines de voix de synthèse multilingues, plus un corpus réel crowdsourcé et des heures de négatifs) ;
   - Porcupine (Picovoice). **[NV]** Licence et coût pour une distribution gratuite à grande échelle, à vérifier.
   - d'autres moteurs libres.

   Le critère est la meilleure détection à 1 faux réveil par heure.
2. **Phrase de réveil.** La choisir pour sa robustesse : 3 ou 4 syllabes, phonèmes distinctifs, rare dans le vocabulaire du jeu. « Docteur » seul réveillait déjà.
3. **Calibrage au premier lancement.** 5 prises servent à **régler le seuil** pour l'utilisateur, pas à entraîner.
4. **Mode « écoute coupée ».** Automatique quand le joueur parle sur Discord en continu, en option.
5. **Défaut.** Garder le mode touche par défaut tant que le critère n'est pas atteint.

**Critères de réussite.**

- Détection supérieure ou égale à 95 % sur au moins 50 locuteurs jamais vus, avec bruit de jeu à 10 dB.
- Moins d'un faux réveil par heure sur au moins 10 h de discussion et de jeu (corpus de L5).
- Coût en veille inférieur à 1 % du processeur total sur la configuration minimale.

---

### L11 Robustesse audio : micro, bruit, écho (P1, M)

**Objectif.** Capter correctement quel que soit le matériel : micro USB ou intégré, casque ou haut-parleurs.

**Justification.**

- U3 et U16.
- Le niveau faible du micro a été un problème mesuré (crête médiane vers 2 000 sur 32 767).
- En mode touche, il n'y a pas de pré-enregistrement : la trame du front montant est donnée au détecteur, pas à la capture (`app.py`, `record_while`). Le début de la phrase peut être coupé. **[NV]** À mesurer.
- Le bip de réveil peut être capté sur haut-parleurs.

**Fichiers.** `src/drvocal/audio/mic.py`, `src/drvocal/app.py` (`Ears`, `Timings`), nouveau `src/drvocal/audio/dsp.py`.

**Tâches.**

1. **Choix du périphérique.** Par identifiant stable. Suivre le changement de périphérique par défaut et le branchement à chaud.
2. **Format.** Ouvrir le périphérique à son taux natif et rééchantillonner vers 16 kHz. **[NV]** 16 kHz n'est pas garanti en WASAPI.
3. **Contrôle automatique de gain** léger avant le VAD et la transcription.
4. **Réduction de bruit et annulation d'écho.** Réduction de bruit (RNNoise ou WebRTC APM). Annulation d'écho avec la sortie système comme référence, activée si le joueur est sur haut-parleurs.
5. **Pré-enregistrement en mode touche.** Garder 300 ms de tampon circulaire pour ne pas couper la première syllabe.
6. **Bip pendant la capture.** L'ignorer : retirer ses trames ou décaler le début de la capture.
7. **Délais.** Rendre `Timings` réglable.

**Critères de réussite.**

- Sur 4 micros (intégré portable, casque USB, micro XLR via interface, webcam), le taux d'intents justes est supérieur ou égal à 90 % (corpus de L9).
- Sur haut-parleurs, la musique du jeu à volume normal ne déclenche pas de réveil sur 1 h de test.
- Aucun énoncé du corpus ne perd son premier mot en mode touche.

---

### L12 API d'extension (plugins) (P1, L)

**Objectif.** Ajouter une commande sans toucher au cœur, en gardant le catalogue fermé comme barrière.

**Justification.** Section 3.3 : `ACTION_NAMES` est figé dans `actions.py`, les regex sont dans `intent.py` et le câblage dans `__main__.py`.

**Fichiers.** `src/drvocal/actions.py`, `src/drvocal/intent.py`, `src/drvocal/__main__.py`, nouveau `src/drvocal/plugins/`. **Séquentiel avec L13.**

**Tâches.**

1. **Contrat d'extension.** Un manifeste qui donne :
   - le nom ;
   - la version ;
   - les actions, chacune avec un **niveau de risque** (`safe`, `confirm`, `screen_only`) ;
   - les grammaires par langue (motifs avec emplacements nommés) ;
   - les réglages (schéma) ;
   - les permissions (réseau, fichiers, processus).
2. **Catalogue alimenté par les extensions installées.** Les extensions intégrées sont dans le paquet. Une extension tierce ne s'active que par un geste explicite dans les réglages, jamais par une simple présence de fichier.
3. **Niveau de risque appliqué par le cœur.** Une action `confirm` exige une confirmation, et une action `screen_only` ne s'exécute jamais à la voix seule.
4. **Kit de test.** Une fonction `assert_parses(plugin, "phrase", action, slots)` et un exemple d'extension (« minuteur »).
5. **Migration.** Les intégrations existantes (médias, Spotify, Discord, notes, Claude) deviennent des extensions intégrées.

**Critères de réussite.**

- L'extension d'exemple s'ajoute avec un seul nouveau dossier, sans modification de `src/drvocal/*.py` hors `plugins/`.
- Tous les tests existants passent.
- Une extension qui déclare une action inconnue ou mal formée est refusée au chargement (test).

---

### L13 Compréhension : corpus réel et grammaire déclarative (P1, M) (après L12)

**Objectif.** Comprendre du premier coup les formulations variées de nombreux joueurs.

**Justification.**

- La grammaire actuelle est réglée sur les transcriptions d'un seul utilisateur : les exceptions « mais/mai/may » et « dj » viennent de ses captures.
- U12.

**Fichiers.** `src/drvocal/intent.py` et les grammaires des extensions.

**Tâches.**

1. **Corpus.** Recueillir les formulations de 30 joueurs ou plus (questionnaire écrit puis enregistrements), et l'annoter en intent et emplacements.
2. **Grammaires déclaratives.** Les règles d'`intent.py` deviennent des grammaires déclarées. Garder les heuristiques de correction de transcription, mais documentées et testées par corpus.
3. **Repli flou.** Correspondance approximative sur les débuts de phrase connus, uniquement pour les actions `safe`. Jamais de devinette sur `confirm` ni `screen_only`.
4. **Retour visuel.** Afficher « compris : X » dans la notification ou l'indicateur, pour que l'utilisateur apprenne les formulations.

**Critères de réussite.**

- Taux d'intents justes supérieur ou égal à 95 % sur le corpus de test tenu à part.
- 0 % d'action à risque déclenchée sur un ensemble de 500 phrases de conversation de jeu (négatifs).

---

### L14 Garde-fous anti-cheat et sobriété en jeu (P1, M)

**Objectif.** Garantir par construction que Dr Vocal ne touche jamais au jeu et ne lui vole pas de ressources.

**Justification.** U13 et section 5.4. C7.

**Fichiers.** Nouveau `src/drvocal/game_guard.py`, `src/drvocal/actions_hotkeys.py`, `src/drvocal/__main__.py`. **Séquentiel avec L4** pour `actions_hotkeys.py`.

**Tâches.**

1. **Détection du jeu au premier plan.** Utiliser le processus au premier plan, le mode plein écran, et une liste de processus de jeux et d'anti-cheats connus (`vgc.exe`, `EasyAntiCheat*.exe`, `BEService.exe`, `FACEIT*.exe`, etc.).
2. **Blocage.** Quand un jeu est au premier plan, **refuser** tout `SendInput` et toute ouverture d'application qui prendrait le focus.
3. **Priorité.** Mettre le processus en `BELOW_NORMAL_PRIORITY_CLASS`, avec EcoQoS (`SetProcessInformation` avec `ProcessPowerThrottling`) en veille. Limiter les threads d'onnxruntime et de CTranslate2.
4. **Fenêtre.** Charger WebView2 seulement quand il y a quelque chose à afficher. **[NV]** Coût RAM de WebView2 à mesurer, dans le cadre de L5.
5. **Politique publiée.** `docs/anti-triche.md` devient une politique générale :
   - aucune injection ;
   - aucun hook ;
   - aucune lecture mémoire ;
   - aucune touche vers le jeu.

**Critères de réussite.**

- Un test vérifie que, si un processus de jeu est au premier plan (simulé), `send_keys` n'est jamais appelé.
- Mesure L5 : le processus est en priorité inférieure à la normale, et l'utilisation du processeur pendant une transcription est plafonnée au nombre de threads choisi.

---

### L15 Diagnostic et support (P1, M) (dépend de L2)

**Objectif.** Pouvoir aider un utilisateur qu'on ne voit pas.

**Fichiers.** `src/drvocal/__main__.py`, `src/drvocal/actions.py`, nouveau `src/drvocal/diagnostics.py`.

**Tâches.**

1. **Journaliser les exceptions des actions.** Corriger C6 : journaliser dans `Catalogue.run`.
2. **Export de diagnostic.** Un bouton « Exporter un diagnostic » produit un zip avec :
   - le journal ;
   - la version ;
   - la configuration **sans secrets** ;
   - le matériel (processeur, carte graphique, micros) ;
   - les dernières latences.

   Les secrets sont masqués par motif (`token`, `key`, `Bearer`, etc.).
3. **Rapport de plantage, en option** (Sentry ou équivalent), sans audio ni transcription.
4. **Page « État ».** Elle indique ce qui marche : micro, modèles, Spotify, Discord, Claude.

**Critères de réussite.**

- Test : un zip exporté ne contient aucune valeur du magasin de secrets.
- Une exception dans une action apparaît dans le journal avec sa trace.

---

### L16 Qualité : CI, lint, fins de ligne, Python 3.13 (P1, S)

**Fichiers.** `.gitattributes`, `pyproject.toml`, `.github/workflows/ci.yml`, `tests/test_wake.py`.

**Tâches.**

1. Ajouter `.gitattributes` (`* text=auto eol=lf`, binaires marqués) et renormaliser. Cela corrige C5.
2. Ajouter ruff et pyright (ou mypy) en CI sur `windows-latest`.
3. Lancer les tests lents chaque nuit, avec les modèles en cache.
4. Corriger C4 : régénérer la fixture ou marquer le test comme attendu en échec avec sa raison.
5. Préparer Python 3.13 (C8) : `audioop-lts`, ou rendre discord.py facultatif (extra `discord`).

**Critères de réussite.**

- La CI est verte sur chaque PR.
- `git status` est propre après un checkout sous Windows.
- `pip install drvocal` sans l'extra discord fonctionne en 3.13.

---

### L17 Mises à jour automatiques (P1, M) (dépend de L7)

**Tâches.**

1. Vérifier les mises à jour signées : GitHub Releases et Velopack (ou WinSparkle).
2. Ne jamais mettre à jour pendant qu'un jeu est au premier plan.
3. Migrer la configuration avec `schema_version` (L2).
4. Prévoir un canal bêta.

**Critères de réussite.**

- Passage de la version N à N+1 sans action de l'utilisateur, avec les réglages conservés.
- Retour arrière possible.
- Une mise à jour non signée est refusée (test).

---

### L18 Documentation et spec multi-utilisateurs (P1, S) (après les décisions de la section 8)

**Tâches.**

1. Réécrire la spec : intention « tout joueur PC », objectifs, anti-objectifs (ajouter « fuite de secret » et « dépendance à un compte tiers pour les fonctions de base »).
2. Écrire des ADR pour chaque décision de la section 8.
3. Séparer le README utilisateur (installation en 3 étapes, commandes) du guide développeur (`CONTRIBUTING.md` : tests, outils, entraînement du réveil).
4. Créer une vraie `ROADMAP.md` qui reprend la section 9.
5. Marquer le plan `docs/superpowers/plans/…` comme historique (cases à mettre à jour).

**Critères de réussite.**

- Plus aucune mention de « un seul utilisateur » hors historique.
- Le README utilisateur ne contient aucune commande de terminal.

---

### L19 Fonctionnement avec un seul écran (P1, M)

**Objectif.** Les retours et les demandes en attente sont visibles sans deuxième écran, sans couvrir le jeu.

**Justification.** U10. Aujourd'hui, avec un seul écran, la fenêtre reste masquée.

**Fichiers.** `src/drvocal/screen.py`, `src/drvocal/__main__.py`, nouveau `src/drvocal/notify.py`.

**Tâches.**

1. **Un seul écran détecté.**
   - Pas de fenêtre pendant le jeu.
   - Notifications Windows (toast) seulement si aucun jeu plein écran n'est au premier plan (L14).
   - Sinon, mise en file d'attente, avec un badge sur l'icône de notification.
2. **Demandes en attente.** Elles s'affichent dans la fenêtre Réglages, onglet « Claude », après la partie.
3. **Paramètre d'affichage.** `display_mode` prend la valeur `auto`, `second_screen`, `notifications` ou `none`.

**Critères de réussite.**

- Avec un seul écran, une demande Claude en attente est visible depuis l'icône de notification.
- Aucune fenêtre ni notification n'apparaît par-dessus un jeu plein écran (test manuel avec un jeu).

---

### L20 Anglais et multilingue (P2, L) (après L13)

- Langue de la transcription configurable, ou détection automatique limitée aux langues activées.
- Grammaires par langue dans les extensions.
- Phrases de confirmation par langue.
- Voix Piper par langue.

**Critère de réussite.** Le corpus anglais atteint les mêmes seuils que L9 et L13.

### L21 Profils par jeu (P2, M) (après L14)

- Détection du jeu.
- Par jeu : touche de réveil, mode réveil coupé, autorisation ou non des raccourcis simulés, volume des bips.

**Critère de réussite.** Changer de jeu applique son profil sans action de l'utilisateur.

### L22 Commandes cachées aux amis : micro virtuel (P3, XL) (après L4)

**Objectif.** Les amis sur Discord n'entendent pas « mets Daft Punk ».

**Approche.** Un périphérique audio virtuel que Discord utilise comme micro. Dr Vocal y recopie le micro réel, sauf pendant une commande.

**Coût.** Un pilote signé (ou une solution tierce intégrée) : lourd, d'où P3.

**Critère de réussite.** Pendant une commande, les amis entendent du silence, avec une latence ajoutée inférieure à 20 ms le reste du temps.

### L23 Approbations Claude depuis le téléphone (P3, L) (après L1 et L19)

- Lier un appareil par code QR, sur le réseau local ou par relais chiffré de bout en bout.
- Voir et approuver les demandes en attente pendant la partie, sans toucher au PC.

**Critère de réussite.** Une demande est approuvée depuis le téléphone en moins de 10 s, et le canal est authentifié et chiffré.

## 8. Décisions produit à trancher (par l'auteur) avant de lancer les lots

1. **Licence du projet** : open source (laquelle ?) ou propriétaire gratuite. Elle conditionne L6 et le choix du moteur de réveil (L10).
2. **Mécanisme par défaut pour « coupe mon micro »** (L4) : coupure Windows, ou rien par défaut. À trancher après le prototype de L4, étape 1.
3. **Garder ou non le bot Discord** dans le produit (maintenance contre public cible : peu de joueurs sont administrateurs).
4. **Claude** : fonction de lancement ou extension facultative ? Avec une clé API, c'est payant pour l'utilisateur. Faut-il contacter Anthropic pour l'usage du CLI déjà connecté (section 5.3, [NV]) ?
5. **Moteur de réveil** (L10) : open source entraîné par nous, ou commercial.
6. **Télémétrie facultative** : oui ou non. Elle change ce que L15 peut mesurer en production.
7. **Langues** : français seul au lancement, ou français et anglais.

## 9. Ordre conseillé (jalons)

- **Jalon 0, socle (environ 2 semaines).**
  - En parallèle : L16, L6, L5 (banc), L1, L2.
  - Puis, en parallèle : L3 et L4.
  - Résultat : un produit sûr et légal, qui fonctionne sans aucun compte, encore installé par terminal.
- **Jalon 1, bêta privée (environ 4 semaines).**
  - L7 et L8 en parallèle, puis L19, L15 et L14.
  - L9 lancé dès que L5 donne des chiffres.
  - Résultat : un installateur et un assistant de premier lancement, testés par 20 joueurs.
- **Jalon 2, référence.**
  - L10 (le plus long, à démarrer tôt en tâche de fond), L11, puis L12, puis L13, puis L17 et L18.
- **Ensuite.** L20, L21, L22 et L23.

## 10. Ce que cette revue n'a pas pu vérifier

- Les licences exactes des voix Piper, des modèles openWakeWord et de Whisper/CTranslate2 (L6).
- Les conditions et le coût de Porcupine pour une distribution gratuite (L10).
- La procédure de vérification des bots Discord et des intents privilégiés au-delà de 100 serveurs.
- L'existence d'une procédure publique d'approbation du RPC vocal.
- Si l'appel du CLI `claude` déjà connecté de l'utilisateur est permis pour une application tierce.
- Si spotipy 2.26 appelle l'endpoint remplacé `/me/tracks`.
- Le comportement réel de :
  - `os.startfile("spotify:")` (focus) ;
  - la coupure d'un endpoint de capture vis-à-vis de Dr Vocal ;
  - l'ouverture du micro à 16 kHz en WASAPI ;
  - la perte de la première syllabe en mode touche.
- Toute mesure en jeu : FPS, latence de bout en bout, faux réveils réels. Il n'en existe aucune dans le dépôt.
- Les 5 tests lents (non lancés).
