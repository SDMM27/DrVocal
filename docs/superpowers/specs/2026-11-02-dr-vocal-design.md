# Dr Vocal : conception

Date : 2026-11-02. Plateforme : Windows 11. Usage personnel, un seul utilisateur.

Les éléments marqués **[Décision de Claude]** n'ont pas été choisis par l'utilisateur, qui a délégué tous les choix techniques avec trois critères : le plus performant, le plus personnalisable, le moins gourmand possible pour ne pas faire lagger le jeu.

## Intention

L'utilisateur joue à Rocket League, CS2, Red Dead Redemption 2, Pummel Party et Cyberpunk 2077, les deux mains prises. Aujourd'hui, lancer Spotify ou un prompt Claude l'oblige à faire un alt-tab, donc à arrêter de jouer. Dr Vocal est un assistant vocal permanent : il écoute, comprend une demande en français et l'exécute sans jamais sortir l'utilisateur de son jeu.

## Objectifs

1. **Réveil vocal** par une seule phrase au départ : « salut doc vocal » (écrite ainsi pour la synthèse et la transcription). Les quatre salutations avec « docteur » ont été abandonnées le 2026-11-03 : moins de la moitié étaient reconnues et « docteur » seul réveillait (voir `docs/mesures.md`). La liste est modifiable.
2. **Spotify** (compte Premium) : lancer un titre, un album, un artiste ou une playlist par son nom ; pause, reprise, suivant, précédent, volume.
3. **Discord, sa propre voix** : se muter, se mettre en sourdine, en simulant les raccourcis globaux déjà configurés par l'utilisateur.
4. **Discord, serveurs dont l'utilisateur est administrateur** : écrire un message, se déplacer de salon vocal, muter un autre utilisateur.
5. **Prompts Claude Code à la voix, en précisant le projet** : Claude Code travaille en arrière-plan et s'affiche sur le deuxième écran. Dr Vocal ne parle que si Claude a besoin d'une réponse pour continuer.
6. **Prise de notes à la voix** : le texte dicté est enregistré mot pour mot dans un fichier `.txt` d'un dossier NOTES facile à retrouver.
7. **Personnalisation** : mots de réveil, commandes, synonymes, raccourcis, salons, surnoms, voix et sons se règlent dans un fichier, sans toucher au code. Ajouter une nouvelle action reste simple (voir Architecture).

## Non-objectifs

- Fonctionner sur un autre système que Windows, ou pour plusieurs utilisateurs.
- Conversation libre avec Dr Vocal lui-même : il exécute des actions, et tout échange ouvert passe par Claude.
- Application avec une interface graphique riche. **[Décision de Claude]** Le premier affichage reste une simple fenêtre pour Claude sur le deuxième écran.
- Écrire sur Discord depuis le compte de l'utilisateur.

## Anti-objectifs (échec même si « ça marche »)

- **Le jeu lagge** ou perd le focus à cause de Dr Vocal.
- **Dr Vocal supprime des fichiers, ou ferme le jeu ou Discord**, sur une erreur de compréhension. Ces actions n'existent pas dans son catalogue : l'impossibilité vaut mieux qu'une confirmation vocale, elle-même sujette à erreur.
- **Dr Vocal écrase une note existante.** Chaque note crée un nouveau fichier.
- **Dr Vocal déclenche une sanction anti-triche** dans un jeu.
- **Il se déclenche sans arrêt** pendant que l'utilisateur parle à ses amis sur Discord.
- **Il parle pour rien** par-dessus la partie.
- **L'audio part sur internet** avant le mot de réveil.

## Contraintes

- **Machine :** Ryzen 7 5700 (8 cœurs), RTX 4060 8 Go, 16 Go de RAM. La RAM et la mémoire vidéo sont partagées avec le jeu.
- **Installé :** Claude Code 2.1.286, Python 3.14, Node 25, uv. Pas de Rust ni de .NET.
- **Micro partagé avec Discord :** les amis de l'utilisateur entendent ce qu'il dit à Dr Vocal. C'est accepté.
- **Casque :** l'utilisateur joue au casque, donc le son du jeu et de Discord n'arrive pas dans le micro. Pas de traitement de l'écho. Dr Vocal capture directement le micro physique ; FxSound est présent sur la machine mais traite la sortie audio.
- **Abonnement Claude Pro, sans paiement à l'usage.** Claude Code est piloté avec la connexion déjà présente sur le PC. Selon le centre d'aide d'Anthropic (mise à jour du 15 juin 2026), le mode automatisé puise dans les limites de l'abonnement. Aucune clé API n'est utilisée : définir `ANTHROPIC_API_KEY` ferait basculer la facturation. L'usage de Dr Vocal partage les limites de Pro avec le reste. Cette règle d'Anthropic peut changer, comme l'avait annoncé le projet suspendu en juin.
- **Discord interdit l'automatisation d'un compte utilisateur** (à confirmer dans ses règles). Aucun selfbot, quel que soit l'usage.
- **Spotify :** le contrôle de lecture demande Premium. Selon des sources tierces à vérifier, le propriétaire d'une application en mode développement doit aussi être Premium depuis 2026, ce qui est le cas ici.

## Comportement

**Boucle normale :** mot de réveil → petit son → l'utilisateur parle → la fin de phrase est détectée → la demande est transcrite → l'action est exécutée → petit son de succès ou d'échec. Pas de voix par défaut, pour ne pas couvrir le jeu.

**Incompréhension :** un son d'échec et aucune action. Dr Vocal ne devine jamais une action à risque. **[Décision de Claude]**

**Faux réveil :** si aucune parole ne suit dans un délai court, il retourne en veille. **[Décision de Claude]**

**Messages Discord :** une transcription erronée serait publique. Dr Vocal relit donc le message à voix haute, puis l'envoie après un court délai, sauf si l'utilisateur dit « annule ». **[Décision de Claude]**

**Mute d'un autre utilisateur :** le bot applique un mute serveur, visible et valable pour tout le monde, seul mute qu'un bot puisse appliquer. **[Décision de Claude]** Le nom doit correspondre à un membre connu ou à un surnom configuré, sinon aucune action.

**Notes :** une phrase comme « prends une note » lance la dictée, avec un silence de fin plus long que pour une commande. Chaque note crée un fichier `.txt` daté dans le dossier NOTES, jamais d'écrasement. **[Décision de Claude]** Emplacement par défaut : `Documents\NOTES`, modifiable.

**Changer de mot de réveil :** chaque phrase demande son propre modèle. Modifier la liste passe donc par le fichier de réglages, puis par une commande unique qui génère le modèle ; l'effet n'est pas immédiat. Si aucun moteur n'atteint la cible, le dernier recours est une touche ou un bouton de manette à maintenir pour parler. **[Décision de Claude]**

**Réponses vocales à Claude :** **[Décision de Claude]**
- Une autorisation ne s'accepte que par une phrase précise, « oui docteur », pour qu'un « oui » adressé à un ami ne compte pas.
- Sans réponse comprise, l'action n'est pas exécutée et la demande reste en attente sur le deuxième écran, où elle peut être traitée après la partie.
- Les lectures de fichiers ne demandent jamais d'autorisation, pour éviter d'interrompre la partie à chaque étape.

**Claude :**
- L'utilisateur nomme le projet à l'oral. Les noms parlés sont associés aux dossiers dans les réglages. Projet inconnu : aucune session lancée. **[Décision de Claude]**
- La demande ouvre une session dans ce dossier, ou continue la session en cours si l'utilisateur le dit.
- Les modifications de fichiers dans le projet passent sans question, sinon chaque étape interromprait la partie. Les commandes et tout accès hors du projet demandent une autorisation. **[Décision de Claude]**
- La progression et les réponses s'affichent sur le deuxième écran.
- Si Claude pose une question ou demande une autorisation, Dr Vocal la lit en résumé et attend une réponse vocale. La réponse s'obtient sans mot de réveil, dans une courte fenêtre d'écoute.
- Le reste du temps, il garde le silence, puis émet un son discret quand Claude a fini.
- Les autorisations de Claude Code restent actives : jamais de mode qui les contourne.
- Les commandes destructives (suppressions massives, formatage, arrêt de processus) sont refusées d'office par des règles, sans proposition vocale. **[Décision de Claude]**
- Limite assumée : ces règles réduisent le risque sans offrir la garantie absolue du catalogue de Dr Vocal, car Claude garde ses capacités normales dans le projet. Une commande autorisée à tort pourrait agir au-delà des règles, d'où l'autorisation explicite pour chaque commande non listée. **[Décision de Claude]**

## Architecture **[Décision de Claude]**

Un seul programme Python (3.12 ou 3.13 selon les paquets compatibles, géré par uv), lancé au démarrage de Windows. Les composants sont interchangeables pour pouvoir changer de moteur sans tout réécrire.

| Partie | Choix de départ | Pourquoi |
|---|---|---|
| Mot de réveil | openWakeWord (modèles entraînés sur les phrases voulues), sur processeur | Local, gratuit, très léger, pas de limite de licence. Repli : Porcupine si le français ou les faux réveils posent problème |
| Fin de phrase | Silero VAD, sur processeur | Léger, chargé seulement après le réveil |
| Transcription | faster-whisper sur processeur par défaut, modèle retenu par les mesures | Local, gratuit, bon en français ; ne travaille qu'après le réveil ; Cyberpunk et RDR2 peuvent saturer les 8 Go de mémoire vidéo |
| Compréhension | Règles et grammaire locales uniquement. Pour Claude, la phrase est transmise telle quelle | Instantané, gratuit, ne consomme pas l'abonnement ; ne peut pas inventer d'action |
| Voix | Piper, français, sur processeur | Local, léger, ne sert que rarement |
| Spotify | API Web de Spotify, authentification PKCE | Seule voie pour lancer un titre par son nom sans focus |
| Discord, soi-même | Touches simulées (SendInput) vers les raccourcis globaux | Aucune autorisation, quasi instantané |
| Discord, serveurs | Bot personnel (discord.py), invité sur les serveurs de l'utilisateur | Voie autorisée ; les messages paraissent sous le nom du bot |
| Claude | Claude Code installé, piloté en arrière-plan via l'Agent SDK en Python ou directement en `claude -p`, connexion de l'abonnement, avec interception des autorisations et des questions | Pas de paiement à l'usage ; sait distinguer quand Claude a besoin de l'utilisateur |
| Deuxième écran | Petite fenêtre locale placée sur le deuxième écran | Pas de focus volé au jeu |
| Réglages | Fichier TOML, secrets dans un fichier séparé hors de git | Personnalisable sans code |

Chaque action est un module enregistré dans un catalogue explicite. Seules les actions du catalogue sont exécutables : le catalogue est la barrière de sécurité.

Les fenêtres de Dr Vocal ne doivent jamais prendre le focus.

## Mesures qui valident le projet

Cibles fixées par Claude, à ajuster après mesure :

- **Impact sur le jeu :** pas de baisse perceptible d'images par seconde, en veille comme pendant une transcription. Mesuré sur le plus lourd (Cyberpunk 2077), puis vérifié sur Rocket League et CS2 pour les jeux où la réactivité compte.
- **En veille :** moins de 2 % du processeur total et moins de 300 Mo de RAM.
- **Réactivité :** moins d'une seconde entre la fin de la phrase et l'action, pour les commandes courantes.
- **Faux réveils :** moins d'un par heure de discussion réelle sur Discord.
- **Compréhension :** mesurée sur un jeu de phrases en français enregistrées, avec le bruit du jeu.

Le choix du modèle de transcription et de son emplacement (processeur ou carte graphique, gardé en mémoire ou chargé à la demande) se fait à partir de ces mesures, en jeu.

## Risques à vérifier tôt

1. **Mots de réveil :** entraîner openWakeWord sur des phrases françaises et italianisantes n'est pas prouvé. Peut justifier le repli.
2. **Raccourcis Discord :** Discord doit capter la touche simulée avec le jeu au premier plan, et le jeu ne doit pas y réagir.
3. **Anti-triche :** chercher ce que VAC (CS2) et l'anti-triche de Rocket League disent de la simulation de touches avant tout test en ligne. **[Décision de Claude]** Les premiers essais se font hors ligne. Au moindre doute, le mute de soi passe par un autre moyen, et aucune touche n'est jamais simulée vers le jeu.
4. **Pilotage de Claude Code :** vérifier tôt que le mode automatisé, avec la connexion Pro, remonte bien les questions et les autorisations.
5. **Spotify :** confirmer les règles 2026 du mode développement dans la documentation officielle.

## Laissé au constructeur

- Découpage du code, tests, journalisation, format exact du fichier de réglages.
- Réglage des seuils, délais et sons.
- Packaging et démarrage automatique.
- Ordre de construction, à condition de valider tôt le mot de réveil et l'impact sur le jeu, dont tout le reste dépend.
