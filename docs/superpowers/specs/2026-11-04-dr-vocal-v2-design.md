# Dr Vocal v2 : conception

Date : 2026-11-04. Prolonge `2026-11-02-dr-vocal-design.md`, qui reste valable pour tout ce qui n'est pas modifié ici (machine, contraintes, anti-objectifs, choix audio).

Les éléments marqués **[Décision de Claude]** n'ont pas été choisis par l'utilisateur. Les autres viennent de la conversation du 2026-11-04.

## Intention

L'utilisateur veut **un « Siri » pour son PC** : une app qui tourne en fond en permanence, démarre avec Windows, attend la phrase de réveil, puis exécute ce qu'on lui dit, ou y répond. Il veut s'en servir avec Spotify, Discord et Claude Code « comme il le veut », puis pour des tâches comme envoyer des mails, faire des recherches sur internet et poser des questions. Pour tout ce qui engage quelque chose, il veut une confirmation vocale avant l'action.

Il doit pouvoir s'en servir sans toucher à la souris ni au clavier, souvent en pleine partie.

## Constat au 2026-11-04 (premier usage réel)

- **« Salut doc vocal » ne fait rien** parce que Dr Vocal ne tourne pas. Le PC a démarré à 21h34. Le lancement automatique (clé `Run` → `.venv\Scripts\pythonw.exe -m drvocal`) n'a rien écrit dans le journal, pas même la ligne « demarrage ». Lancé à la main depuis un autre dossier, il démarre normalement. La cause n'est pas connue et l'échec est silencieux.
- **Un titre précis ne se lance pas.** « Je joue Rubly de Dariana sur Spotify » a été compris, mais après `start_playback(uris=[...])`, Spotify ne lit pas (`is_playing=False`, appareil `MISSILE_SATAN`, deux fois). Dr Vocal remet alors la musique d'avant. Les artistes, les playlists et le DJ (lancés par `context_uri`) fonctionnent.
- **« Mets en boucle » a lancé le titre « En boucle » de GP Explorer.** La commande « répéter » n'existe pas, donc la phrase est tombée dans la recherche de musique.
- **Le Spotify de l'utilisateur est en russe.** « Joue ma playlist На повторе » (la playlist générée « En boucle », *On Repeat*) a été transcrit « na paftory » et n'a pas été compris. Le DJ, lui aussi une playlist générée par Spotify, se lance par son URI : on suppose donc que « На повторе » se lancera de la même façon si on connaît son URI.
- Faux réveils encore présents sur le souffle du micro (voir `docs/mesures.md`, correctif de fond non fait).

## Découpage en étapes

Chaque étape est utilisable seule et s'appuie sur la précédente.

1. **Fondations** : app en fond fiable, correctifs Spotify, Discord en local.
2. **Le cerveau** : compréhension des phrases libres par un modèle de langage, qui choisit parmi les actions du catalogue. Essai comparatif entre Claude et un modèle local.
3. **Il répond** : questions, recherches internet, réponses dites dans le casque, dialogue de confirmation généralisé.
4. **Les comptes** : mails d'abord (lire, résumer, écrire, envoyer après confirmation), puis agenda et autres, une intégration à la fois.

**Ce document détaille les étapes 1 et 2.** Les étapes 3 et 4 sont décrites ici comme une vision. Elles auront leur propre conception et leur propre plan une fois l'étape 2 mesurée, parce que l'essai de l'étape 2 décide du moteur.

## Règles qui ne changent jamais

Ces règles valent pour toutes les étapes, y compris quand un modèle de langage interprète les phrases :

- **Seules les actions du catalogue sont exécutables.** Un modèle de langage choisit une action du catalogue avec des arguments validés, ou ne fait rien. Il n'exécute jamais de code ni de commande système de lui-même.
- **Aucune action ne supprime de fichier, ni ne ferme le jeu ou Discord.** Ces actions ne sont jamais ajoutées au catalogue.
- **Toute action visible par d'autres ou irréversible est confirmée** avant de partir : message Discord (relecture puis envoi sauf « annule »), prompt Claude Code (comme aujourd'hui), et plus tard mail, invitation, etc. (confirmation par « oui docteur »).
- **L'audio ne quitte jamais le PC.** Seul du texte transcrit peut partir, et seulement après un réveil.
- **Aucune touche n'est simulée vers le jeu** par défaut (`docs/anti-triche.md`).
- **Le jeu ne doit pas lagger ni perdre le focus.**
- **Pas de clé API Anthropic** : Claude passe par l'abonnement Pro déjà connecté.

## Étape 1 : fondations

### 1.1 App en fond fiable

Objectif : Dr Vocal tourne dès la connexion Windows, tout le temps, et l'utilisateur voit d'un coup d'œil s'il écoute.

- **Diagnostiquer d'abord** pourquoi la clé `Run` n'a rien lancé ce soir, avant de remplacer quoi que ce soit. Hypothèses à vérifier : le `pythonw.exe` du venv uv dépend d'un interpréteur de base introuvable à ce moment-là, le lecteur `D:` n'est pas prêt, ou un plantage survient avant l'ouverture du journal.
- **Toute erreur au démarrage laisse une trace**, même si elle survient avant la configuration du journal : un fichier `startup-error.log` dans `%LOCALAPPDATA%\DrVocal`, et une notification Windows.
- **Démarrage robuste.** **[Décision de Claude]** On remplace la clé `Run` par une tâche planifiée Windows, au niveau utilisateur, sans droits administrateur : déclenchée à l'ouverture de session, avec un délai d'environ 30 s, et relancée automatiquement en cas de plantage (3 essais). L'outil `tools/install_autostart.py` installe et retire cette tâche, et retire l'ancienne clé `Run`. Si la tâche planifiée pose problème, le constructeur peut garder la clé `Run` et ajouter un petit superviseur, à condition de respecter les mêmes garanties.
- **Une seule instance** à la fois (verrou nommé). Une seconde instance se ferme proprement en le journalisant.
- **Icône dans la zone de notification** (près de l'horloge), avec trois états visibles : en écoute, en pause, en erreur (un composant optionnel a échoué ou le micro est absent). Le clic droit ouvre un menu : mettre l'écoute en pause, la reprendre, ouvrir le journal, ouvrir la config, quitter. En pause, le micro n'est plus lu du tout. L'icône ne prend jamais le focus.
- **Micro débranché ou changé** : Dr Vocal réessaie d'ouvrir le micro périodiquement au lieu de s'arrêter, et l'icône passe en erreur pendant ce temps. **[Décision de Claude]**

### 1.2 Spotify

- **Titre précis.** Corriger `start_playback(uris=[...])`, qui ne démarre pas la lecture. Commencer par diagnostiquer la cause, sans corriger à l'aveugle. Pistes à vérifier : le relinking des titres (Spotify joue un URI différent de celui demandé, et la vérification `_plays_requested` le prend pour un échec), le marché ou la disponibilité du titre, un appareil cible inactif. Critère de fin : « mets Fausse Richesse de Mc Pao », dit trois fois de suite, lance ce titre à chaque fois.
- **Surnoms de playlists et d'albums** : une table `[spotify.aliases]` dans `config.toml`, de la forme nom parlé → lien ou URI Spotify. Exemple : `"ma playlist en boucle" = "https://open.spotify.com/playlist/37i9dQZF1Ep..."`. Elle est consultée avant la bibliothèque et la recherche, et lance directement par `context_uri`. Elle sert aux playlists générées par Spotify (« En boucle », « Découvertes de la semaine ») et aux noms russes difficiles à dire. Les noms des alias sont ajoutés au vocabulaire de transcription.
- **Répétition et lecture aléatoire**, reconnues avant toute recherche de musique :
  - « mets en boucle », « répète ce titre », « répète la chanson » → répétition du titre ;
  - « répète la playlist », « répète l'album » → répétition du contexte ;
  - « arrête la boucle », « enlève la répétition » → répétition désactivée ;
  - « mode aléatoire », « lecture aléatoire », « mélange » → aléatoire activé ;
  - « arrête l'aléatoire », « enlève l'aléatoire » → aléatoire désactivé.

  « Mets en boucle » ne doit plus jamais déclencher une recherche.

### 1.3 Discord en local

L'utilisateur veut baisser le volume d'une personne **pour lui seul**, comme le curseur du clic droit dans Discord. Un bot ne le peut pas : ce réglage n'existe que dans l'application Discord.

- **Piste retenue : la connexion RPC locale de Discord** (le tube nommé `\\.\pipe\discord-ipc-N`), avec l'application développeur personnelle de l'utilisateur et les permissions `rpc`, `rpc.voice.read` et `rpc.voice.write`. Elle permet de régler le volume d'un membre pour soi (`SET_USER_VOICE_SETTINGS`), de couper son micro et de se mettre en sourdine (`SET_VOICE_SETTINGS`), et de lire le salon vocal en cours avec ses membres (`GET_SELECTED_VOICE_CHANNEL`).
- **Risque à lever en premier, par un essai jetable :** Discord réserve cet accès aux applications validées. On suppose que le propriétaire de l'application peut l'utiliser pour lui-même, mais ce n'est pas vérifié. L'essai doit autoriser l'application une fois et régler le volume d'un membre réel. Le résultat est noté dans `docs/mesures.md`.
- **Si l'essai réussit :**
  - nouvelles actions `discord.member_volume` (« baisse Alex », « baisse Alex à 30 % », « monte Alex », « remets Alex normal ») ;
  - « baisse » sans pourcentage divise le volume actuel par deux, « monte » le multiplie par 1,5 dans la limite de 200 %, et « remets normal » le ramène à 100 %. **[Décision de Claude]** ;
  - le nom est cherché parmi les membres du salon vocal en cours, par pseudo affiché ou par surnom configuré (`[discord.members]`). Plusieurs correspondances ou aucune : rien n'est fait, son d'échec ;
  - « coupe mon micro » et « mets-moi en sourdine » passent par RPC, qui fonctionne aussi en appel privé, hors serveur. Le bot reste un repli si RPC n'est pas connecté ;
  - le jeton d'autorisation est gardé localement, ignoré par git, comme `.spotify-cache`. Si le secret client est nécessaire à l'échange du jeton, il va dans `secrets.toml`.
- **Si l'essai échoue :** le volume par personne est abandonné et documenté comme impossible. Le bot garde le mute et la sourdine. Aucune automatisation de l'interface Discord, qui volerait le focus au jeu.
- **Le bot reste** pour écrire un message, changer de salon et le mute serveur.

### 1.4 Faux réveils (optionnel, en fin d'étape 1)

Réentraîner le modèle de réveil avec quelques minutes de souffle et de bruit de la pièce en négatifs, comme le prévoit `docs/mesures.md`. On ne le fait que si les faux réveils gênent encore une fois l'app vraiment lancée en continu.

## Étape 2 : le cerveau

### 2.1 Comportement

- **Les règles passent en premier**, comme aujourd'hui : synonymes, puis règles locales. C'est instantané, gratuit, et rien ne quitte le PC.
- **Si aucune règle ne reconnaît la phrase**, elle est envoyée à un interpréteur (un modèle de langage). Il reçoit :
  - le texte transcrit ;
  - la description de chaque action du catalogue, avec ses arguments ;
  - les noms connus : projets, alias et bibliothèque Spotify (une partie), salons et membres Discord.
- **Ces noms quittent le PC avec la phrase** : accord explicite de l'utilisateur le 2026-11-04. Le principe « seul du texte transcrit part » s'étend donc à ces noms, et seulement quand le moteur Claude est appelé.
- **Il répond** par une action du catalogue avec ses arguments, ou par « rien ». Il peut corriger un nom mal transcrit en le rapprochant d'un nom connu (« na paftory » → « На повторе »).
- **La réponse est validée** : action existante, arguments du bon type, nom connu quand l'action en exige un. Si elle n'est pas valide, rien n'est fait et un son d'échec retentit. Aucune nouvelle tentative auprès du modèle. **[Décision de Claude]**
- **Les confirmations existantes s'appliquent pareil**, que l'action vienne des règles ou du modèle.
- **Délai maximal de 8 s**, après quoi c'est un échec. Pendant l'attente, un son discret signale que Dr Vocal réfléchit, pour que l'utilisateur sache qu'il n'a pas été ignoré. **[Décision de Claude]**
- **Le journal des commandes** note le moteur qui a compris la phrase (`rules`, `claude`, `local`) et sa durée.
- **Réglage** `brain_engine = "claude" | "local" | "off"`. Défaut : `"claude"` jusqu'à l'essai. **[Décision de Claude]**

### 2.2 Catalogue décrit

Le catalogue (`actions.py`) devient une liste de fiches. Chaque fiche contient le nom, une description en français, les arguments (nom, type, valeurs possibles ou source de noms connus) et un indicateur « sensible », qui impose une confirmation. C'est cette liste qu'on donne au modèle, et c'est elle qui sert à valider sa réponse. Les étapes 3 et 4 ajouteront leurs actions de la même façon.

### 2.3 Moteurs

- **Claude** : via `claude-agent-sdk`, déjà utilisé pour les sessions Claude Code, avec la connexion de l'abonnement et sans clé API. Les clés `ANTHROPIC_*` sont retirées de l'environnement, comme aujourd'hui. Aucun outil n'est autorisé et un seul tour suffit : le modèle ne fait que répondre un JSON. On prend le modèle le plus rapide qui reste juste (Haiku en premier essai). **[Décision de Claude]**
- **Local** : un modèle servi par Ollama. Il n'est chargé que s'il est choisi, et l'essai doit mesurer sa place en mémoire vidéo et en RAM.
- Les deux moteurs respectent la même interface `interpret(text, context) -> Intent | None`, de sorte qu'on change de moteur par la config seulement.

### 2.4 Essai comparatif

Un outil `tools/bench_brain.py` fait passer un jeu de phrases aux deux moteurs et mesure :

- la justesse : action et arguments attendus ;
- le délai médian et le 95e centile ;
- la mémoire vidéo et la RAM utilisées ;
- avec un jeu lancé, la baisse d'images par seconde.

Le jeu de phrases compte environ 40 phrases et inclut les vrais échecs du journal : « J'ai eu ma playlist, na paftory sur Spotify », « Jume playlist, na paftory sur Spotify », « mets en boucle », « Je joue Rubly de Dariana sur Spotify ». Il contient aussi des phrases qui ne doivent **rien** déclencher (discussion de jeu entre amis), pour vérifier que le modèle sait répondre « rien ». Les résultats et la décision vont dans `docs/mesures.md`.

**Critère de choix** **[Décision de Claude]** : le moteur local n'est retenu que s'il atteint au moins la justesse de Claude moins 5 points, sous 3 s au 95e centile, sans baisse perceptible d'images par seconde dans Cyberpunk 2077. Sinon, on garde Claude.

## Étapes 3 et 4 : vision (non détaillées ici)

- **Réponses** : « Quelle heure est-il à Tokyo ? », « Cherche les patch notes de Rocket League ». La réponse est courte, dite par Piper dans le casque, et le détail s'affiche sur le deuxième écran. La recherche internet passe par le moteur choisi à l'étape 2 (Claude sait déjà chercher sur le web). La règle actuelle « il ne parle pas pour rien » devient « il ne parle que pour répondre à une question qu'on lui a posée ».
- **Confirmation généralisée** : « J'envoie ce mail à Paul : … Je l'envoie ? » → « oui docteur » ou « non docteur », sur le modèle des autorisations Claude actuelles.
- **Mails** : lire les derniers, les résumer, écrire, envoyer après confirmation. Le fournisseur et le mode d'accès restent à décider à l'étape 4.
- Chaque nouvelle capacité est une action du catalogue avec sa fiche, jamais un accès libre au PC.

## Non-objectifs des étapes 1 et 2

- Répondre aux questions, chercher sur internet, parler en dehors des cas actuels (étape 3).
- Mails, agenda, comptes en ligne (étape 4).
- Un agent libre qui pilote la souris, le clavier ou l'interface des applications.
- Une interface graphique riche : l'icône et la fenêtre du deuxième écran suffisent.

## Anti-objectifs ajoutés

- **Il s'arrête sans prévenir.** Un démarrage ou un plantage silencieux, comme le 2026-11-04, compte comme un échec.
- **Le modèle de langage déclenche une action que l'utilisateur n'a pas demandée.** C'est pire qu'un « pas compris ». En cas de doute, le modèle doit répondre « rien ».
- **« Mets en boucle » lance un titre.**

## Précisions après relecture **[Décision de Claude]**

- **Ordre dans 1.3** : l'essai RPC passe avant tout le reste de 1.3, qui en dépend. Il réutilise l'application développeur Discord du bot existant (même identifiant client), en y ajoutant l'URI de redirection et le secret nécessaires. L'utilisateur doit être présent pour autoriser l'application dans Discord une fois.
- **Ordre dans 1.1** : le diagnostic est la première tâche et conditionne la suite. Il demande à l'utilisateur de redémarrer le PC ou de fermer sa session pour reproduire le problème. Le délai de démarrage est réglable (`autostart_delay_s`, 30 par défaut). La tâche planifiée peut lancer un petit script de démarrage qui attend que le dossier du projet soit accessible, si le diagnostic montre que le lecteur `D:` n'est pas prêt à temps.
- **Moteur Claude** : sa faisabilité est vérifiée par un essai au début de l'étape 2 (un tour, aucun outil, modèle choisi, connexion Pro, délai mesuré), avant de construire le reste. Le client reste ouvert entre deux appels si cela réduit le délai, sinon il est relancé à chaque appel.
- **Catalogue unique** : toutes les actions actuelles reçoivent une fiche. Les intentions issues des règles sont validées par les mêmes fiches que celles du modèle. Il n'y a qu'une seule source de vérité.
- **Actions sensibles** : `discord.message`, `claude.prompt` et `claude.continue`, ainsi que `discord.mute_member` quand il est choisi par le modèle (le mute serveur est visible de tous). Pour celles-ci, une action choisie par le modèle est annoncée, puis exécutée seulement après « oui docteur ». Aucun seuil de confiance chiffré : le modèle répond « rien » s'il hésite, et la mesure de l'essai (phrases qui ne doivent rien déclencher) vérifie qu'il le fait.
- **Images par seconde** : la mesure en jeu est une procédure manuelle décrite dans `docs/mesures.md` (compteur intégré au jeu ou PresentMon), pas une partie automatisée de `bench_brain.py`.
- **Alias Spotify** : l'utilisateur colle lui-même les liens (Partager → Copier le lien dans Spotify). Aucun outil de découverte.
- **Icône** : fil d'exécution dans le même processus, qui partage l'état de pause avec la boucle audio.

## Laissé au constructeur

- La bibliothèque de l'icône (par exemple `pystray`) et celle des notifications.
- Le format exact du JSON échangé avec le modèle et le texte des consignes.
- Le modèle local essayé (taille adaptée à 8 Go de mémoire vidéo partagés avec le jeu).
- La forme interne du catalogue décrit, à condition que la validation reste stricte.
- Le découpage du code et des tests, dans le style actuel (tests pytest, fonctions pures testables, appels réseau simulés).
