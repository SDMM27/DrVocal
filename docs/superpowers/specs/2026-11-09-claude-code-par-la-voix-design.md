# Claude Code par la voix (abonnement) : conception

Date : 2026-11-09. Statut : à valider.

## Intention

Pendant une partie, l'utilisateur veut dicter un prompt à Claude Code pour un de ses projets, par exemple « demande à Claude sur GeoGame de corriger le bug du score ». Après la partie, il veut retrouver ce travail dans l'**app desktop Claude** (onglet Code) et le poursuivre au clavier, comme ses autres sessions.

Il ne veut **pas** de clé API Anthropic ni de facturation à l'usage. Le travail passe par son abonnement Claude, via le Claude Code installé sur le PC (`claude`, 2.1.286, déjà connecté).

L'actuel « Claude Agent » (SDK `claude-agent-sdk`, clé API, politique d'autorisations maison, réponses vocales) est **supprimé** et remplacé par ce mode.

## Ce que l'essai du 2026-11-09 a établi

- `claude --bg -n "<nom>" "<prompt>"`, lancé dans un dossier de confiance, démarre une session Claude Code en arrière-plan avec le compte de l'utilisateur. La commande rend la main immédiatement et affiche l'identifiant court (`backgrounded · 915c4b6f · Essai Dr Vocal`). Aucune fenêtre ne s'ouvre.
- `claude agents --json` (sans TTY) liste les sessions actives : `id` court, `sessionId` (UUID), `cwd`, `kind: "background"`, `status` (`busy` puis `idle` une fois le tour terminé), `state`.
- Une fois son tour terminé, la session reste en vie (`idle`). `claude stop <id>` l'arrête et garde la conversation.
- Une session lancée en ligne de commande n'apparaît **pas** d'elle-même dans l'app desktop. Ouvrir `claude://resume?session=<UUID>` l'importe : elle apparaît dans la liste (`local_<UUID>`, même titre). Cet import met l'app au premier plan.
- Dans un dossier sans confiance, `claude --bg` échoue avec « Workspace not trusted ». GeoGame et DrVocal sont de confiance.
- La session de test est partie en mode auto, le réglage par défaut de l'utilisateur.

## Objectifs

1. **Lancer** : « demande à Claude sur <projet> de <prompt> » lance une session Claude Code en arrière-plan dans le dossier du projet (`[projects]`), en mode auto, sans voler le focus. Un bip de succès si le lancement a réussi, un bip d'échec sinon.
2. **Continuer** : « continue avec Claude pour <prompt> » envoie la suite à la dernière session lancée.
3. **Arrêter** : « arrête Claude » arrête la session en cours.
4. **Fin** : quand une session termine son tour, le bip discret `done` (« Claude a fini ») joue.
5. **Importer** : « importe mes sessions Claude » importe dans l'app desktop toutes les sessions lancées et pas encore importées.
6. **Deuxième écran** : la fenêtre existante affiche, pour chaque session, son projet, son nom et son état (lancée, en cours, finie, arrêtée, échec, importée). Le détail du travail de Claude n'est pas affiché.

## Hors périmètre et anti-objectifs

- Aucune clé API, aucun appel direct à l'API Anthropic, aucun SDK Anthropic.
- Pas de réponse vocale aux questions ou demandes d'autorisation de Claude. Si Claude bloque, l'utilisateur le verra en ouvrant la session après l'import.
- Ne jamais voler le focus pendant une partie : ni fenêtre, ni import automatique. L'import se fait seulement sur ordre vocal.
- Ne jamais utiliser `bypassPermissions` ni `--dangerously-skip-permissions`. Le mode est `auto`, choisi par l'utilisateur (« oui il peut »).
- Pas de lecture vocale de ce que Claude a fait.

## Comportement détaillé

### Lancer (`claude.prompt`)

- Projet inconnu ou chemin invalide : échec (bip d'échec), rien n'est lancé. La validation reprend l'idée de `validate_project_root` (refuser la racine d'un lecteur, le dossier personnel, AppData, Windows, Program Files) ; elle est déplacée hors de `claude_policy.py`, qui disparaît.
- Commande lancée, dans le dossier du projet (`cwd`) :
  `claude --bg --permission-mode auto -n "<nom>" "<prompt>"`
  - `<nom>` : « <Projet> – <premiers mots du prompt> », 50 caractères au plus.
  - Le prompt est passé tel que transcrit, en argument (liste d'arguments, jamais de shell, pour éviter toute injection).
  - Exécutable : `claude` trouvé dans le PATH (`shutil.which`), surchargeable par un réglage `claude_command` dans `config.toml`. Introuvable : Claude désactivé au démarrage, comme aujourd'hui sans clé (commandes non enregistrées, message dans le journal).
  - Le processus ne doit ouvrir aucune console visible (`CREATE_NO_WINDOW` sous Windows).
- Succès : la sortie contient l'identifiant court (`backgrounded · <id> · …`). Dr Vocal retrouve l'UUID par `claude agents --json` (entrée de même `id`) et note la session (voir « Registre »). Bip de succès.
- Échec (code de retour non nul, pas d'identifiant, « Workspace not trusted », délai de 30 s dépassé) : bip d'échec, message sur le deuxième écran avec la raison. Pour un dossier sans confiance, le message dit d'ouvrir une fois Claude Code dans ce dossier.

### Continuer (`claude.continue`)

- Cible : la dernière session lancée ou continuée (registre). Aucune : échec.
- Si elle tourne encore (`busy`) : échec, avec le message « Claude travaille encore » sur le deuxième écran. On ne crée pas de copie.
- Sinon : `claude stop <id>` si elle est encore en vie, puis `claude --bg --permission-mode auto --resume <UUID> "<prompt>"` dans le même dossier. L'aide de la CLI dit que cette commande reprend la session sous le même identifiant si elle est arrêtée. **À vérifier dans le plan** : que l'identifiant reste bien le même, et que l'import dans l'app montre toute la conversation.

### Arrêter (`claude.stop`)

- `claude stop <id>` sur la session la plus récente encore en vie. Aucune : succès silencieux (rien à arrêter). Les phrases reconnues ne changent pas.

### Surveiller la fin

- Tant qu'au moins une session notée est en vie, Dr Vocal interroge `claude agents --json` toutes les 5 s, en arrière-plan, sans bloquer l'écoute.
- Passage de `busy` à `idle` : bip `done`, état « finie » sur l'écran, puis `claude stop <id>`. La session libère ainsi la place pour une reprise et pour l'import, et la conversation est gardée.
- Session disparue de la liste sans être passée par `idle` : état « arrêtée ».
- La surveillance s'arrête quand plus aucune session n'est en vie.

### Importer (`claude.import`, nouvelle commande)

- Phrases : « importe mes sessions Claude », « importe les sessions Claude », « importe Claude », « ouvre mes sessions Claude » (variantes à aligner sur le style de `intent.py`).
- Pour chaque session du registre pas encore importée et plus en vie (pas `busy`) : ouvrir `claude://resume?session=<UUID>` (`os.startfile`), puis marquer « importée ». Une session encore `busy` est laissée pour plus tard et signalée à l'écran.
- Rien à importer : succès silencieux.

### Registre

- Fichier JSON dans le dossier de données (`data_dir()`), par exemple `claude_sessions.json` : pour chaque session, `id` court, `uuid`, projet, chemin, nom, date de lancement, état, `imported`.
- Lu au démarrage : les sessions non importées d'avant un redémarrage restent importables.
- Les sessions importées de plus de 7 jours sont purgées au démarrage.

## Suppression de l'ancien Claude Agent

À retirer :
- `src/drvocal/claude_session.py`, `claude_policy.py`, `claude_audit.py` et leurs tests ; `tools/spike_claude.py`.
- La dépendance `claude-agent-sdk` (`pyproject.toml`, `uv.lock`).
- Le secret `claude_api_key` (`SECRET_NAMES`, `SecretStore`) et la lecture de `ANTHROPIC_API_KEY`.
- `make_ask_user` et les réponses vocales à Claude ; les boutons Autoriser / Refuser et les demandes en attente (`pending`) de `screen.py`.
- Les sections du README sur la clé API, la politique d'autorisations, les limites (30 tours, 2 dollars, 15 minutes) et « Répondre à Claude ».

À garder et adapter :
- `screen.py` reste, pour Claude et pour les messages Discord (`notify`). `SessionEvent` (ou son remplaçant) est déplacé dans un module neutre, puisque `claude_session.py` disparaît.
- Le son `done` reste.
- Les phrases de `claude.prompt`, `claude.continue` et `claude.stop` dans `intent.py`.
- Le journal des commandes enregistre toujours le texte des prompts dictés.

## Contraintes du projet

- Python, `uv`. Vérifications : `uv run ruff check .`, `uv run pyright`, `uv run pytest -m "not slow"`.
- Tous les appels à `claude` passent par une petite interface injectable (lancer, lister, arrêter, ouvrir un lien) : les tests n'exécutent jamais le vrai `claude`.
- Appels de processus asynchrones (`asyncio.create_subprocess_exec` ou `to_thread`), jamais dans la boucle d'écoute.
- README en français, dans le ton existant.

## Décisions issues de la relecture (mes décisions, à relire)

- **Session bloquée** (question ou autorisation en attente) : la première étape du plan est un essai qui relève les valeurs `status` / `state` de `claude agents --json` pour une session qui attend une réponse. Règle : seule une session qui travaille vraiment (`busy` avec un `state` de travail, `working` dans l'essai) compte comme « en cours ». Tout autre état vivant compte comme « en attente de toi » : bip `done`, état « en attente » à l'écran, importable, et le verrou du projet est libéré. Une session en attente n'est pas arrêtée par Dr Vocal, pour ne pas perdre la question.
- **Repli si `--resume` ne garde pas le même identifiant** : la reprise est notée comme une nouvelle entrée du registre, liée à la précédente (`parent`). L'import ouvre alors la plus récente. L'essai du plan vérifie aussi que `claude://resume` marche sur une session arrêtée.
- **Continuer une session déjà importée** : refusé. Bip d'échec, et l'écran dit « déjà dans l'app, continue là-bas ». La conversation ne doit jamais se dédoubler entre l'app et l'arrière-plan.
- **Deuxième écran** : il reste un journal d'événements, comme aujourd'hui, partagé avec les messages Discord. Chaque changement d'état d'une session y ajoute une ligne (« GeoGame – corriger le bug… : finie »). Au démarrage, s'il reste des sessions non importées, une ligne le signale (« 2 sessions Claude à importer »).
- **Activation** : pas de réglage on/off en plus. La liste `[projects]` sert d'accord explicite, car Claude ne peut travailler que dans un projet déclaré. Sans `claude` dans le PATH ou sans projet valide, les commandes Claude ne sont pas enregistrées.
- **Clé API déjà enregistrée** : aucune. Le stockage chiffré ne contient que les secrets Spotify, donc il n'y a rien à migrer. Le nom `claude_api_key` est simplement retiré de `SECRET_NAMES`.
- **Ordre des travaux** : le correctif du réveil en pleine phrase, non commité, est commité seul avant de commencer.

## Choix laissés au builder (mes décisions, à relire)

- Intervalle de surveillance : 5 s. Délai de lancement : 30 s.
- Arrêter la session après son tour (`claude stop`) plutôt que la laisser `idle`.
- Pas de worktree (`-w`) : Claude travaille directement dans le dossier du projet, comme l'essai. Une seule session à la fois par projet : un nouveau « demande à Claude sur X » pendant qu'une session de X est `busy` échoue avec un message à l'écran.
- Nom de session « <Projet> – <début du prompt> ».
