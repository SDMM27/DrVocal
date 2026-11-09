# Claude Code par la voix : plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remplacer l'ancien « Claude Agent » (SDK et clé API) par des sessions Claude Code lancées en arrière-plan sur l'abonnement de l'utilisateur, avec la commande `claude --bg`, puis importables dans l'app desktop.

**Architecture:** Une fine couche `claude_cli.py` encapsule tous les appels à l'exécutable `claude` : lancer, lister, arrêter, ouvrir le lien d'import. Un registre JSON (`claude_registry.py`) mémorise les sessions lancées. Un contrôleur (`claude_voice.py`) applique les règles de la spec et une boucle de surveillance. `app.register_claude` branche le contrôleur sur le catalogue d'actions. L'ancien code SDK, la politique d'autorisations et les réponses vocales disparaissent.

**Tech Stack:** Python 3.12, asyncio, uv, pytest (asyncio), ruff, pyright, pywebview (deuxième écran).

**Spec:** `docs/superpowers/specs/2026-11-09-claude-code-par-la-voix-design.md`

## Global Constraints

- Aucune clé API, aucun SDK Anthropic. La dépendance `claude-agent-sdk` est retirée.
- Jamais `bypassPermissions` ni `--dangerously-skip-permissions`. Toujours `--permission-mode auto`.
- Jamais de shell : `asyncio.create_subprocess_exec` avec une liste d'arguments, et `creationflags=subprocess.CREATE_NO_WINDOW` sous Windows.
- Les tests n'exécutent jamais le vrai `claude` : tout passe par l'interface `ClaudeCli`, remplacée par un faux.
- Rien ne vole le focus : l'import (`claude://resume?...`) part seulement de la commande vocale.
- Délai de lancement : 30 s. Intervalle de surveillance : 5 s. Nom de session : 50 caractères au plus. Purge des sessions importées : plus de 7 jours.
- Une seule session « en cours » par projet.
- Vérifications à chaque tâche : `uv run ruff check .`, `uv run pyright`, `uv run pytest -m "not slow"`.
- Textes visibles et README en français ; commits en anglais, avec la ligne `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Prompt dicté contenant des guillemets, des tirets ou commençant par `-`** : il doit arriver à Claude intact, jamais interprété comme une option. Il est passé après `--`, s'il est accepté (à vérifier dans la tâche 1), sinon comme dernier argument. Test dans la tâche 3.
2. **`claude agents --json` qui renvoie autre chose qu'un tableau JSON** (avertissement en tête, sortie vide, code de retour non nul) : la surveillance doit continuer sans planter et sans bip. Test dans la tâche 3, puis dans la tâche 5.
3. **Registre JSON corrompu ou absent au démarrage** : démarrage sans erreur, registre vide, fichier remplacé à la prochaine écriture. Test dans la tâche 4.
4. **Dr Vocal redémarré pendant qu'une session tourne** : au démarrage, la surveillance reprend les sessions du registre encore vivantes, sans rejouer de bip pour celles déjà finies. Test dans la tâche 5.
5. **« Demande à Claude » répété très vite sur le même projet** : un deuxième lancement pendant que le premier est encore en cours de lancement (avant la sortie de `--bg`) doit échouer, et non créer deux sessions. Test dans la tâche 5.

---

### Task 1: Essai des états et de la reprise (session principale, aucun code)

But : figer les valeurs dont dépendent les tâches suivantes. À faire dans `D:/NasaCode/DrVocal`, puis noter les résultats en bas de ce plan, section « Résultats de l'essai ».

- [x] **Step 1 : session bloquée.** `claude --bg --permission-mode manual -n "Essai bloque" "Crée le fichier essai.txt contenant OK"`. Pendant qu'elle attend l'autorisation, relever les champs `status` et `state` dans `claude agents --json`. Les noter comme `WAITING` (états vivants qui ne travaillent pas).
- [x] **Step 2 : états de travail.** Relever `status` / `state` d'une session qui travaille (`busy` / `working` dans l'essai du 2026-11-09) et d'une session finie (`idle`). Noter `WORKING`.
- [x] **Step 3 : reprise.** `claude stop <id>`, puis `claude --bg --permission-mode auto --resume <UUID> -- "Réponds juste OK2"`. Noter si `--` est accepté, si l'identifiant court et l'UUID restent les mêmes, et la ligne exacte affichée.
- [x] **Step 4 : import d'une session arrêtée.** `claude stop <id>`, puis ouvrir `claude://resume?session=<UUID>`. Vérifier qu'elle apparaît dans l'app avec les deux tours.
- [x] **Step 5 : nettoyage.** `claude stop`, puis archiver les sessions d'essai dans l'app ; supprimer `essai.txt` s'il existe.

### Task 2: Déplacer la validation des dossiers de projet

**Files:**
- Create: `src/drvocal/projects.py`
- Modify: `src/drvocal/claude_policy.py` (importe depuis `projects`, temporairement, jusqu'à la tâche 7)
- Test: `tests/test_projects.py` (déplacer les tests `validate_project_root` de `tests/test_claude_policy.py`)

**Interfaces:**
- Produces : `validate_project_root(path: str | Path, env: Mapping[str, str] | None = None, home: Path | None = None) -> str | None`, avec ses helpers `_comparable` et `_is_or_contains`, déplacés tels quels.

- [ ] Step 1 : déplacer la fonction, ses helpers et ses tests. `claude_policy.py` fait `from drvocal.projects import validate_project_root`.
- [ ] Step 2 : `uv run pytest tests/test_projects.py tests/test_claude_policy.py -q`, tout vert.
- [ ] Step 3 : commit `refactor: move project folder validation out of the Claude policy`.

### Task 3: `claude_cli.py`, la couche autour de l'exécutable `claude`

**Files:**
- Create: `src/drvocal/claude_cli.py`
- Test: `tests/test_claude_cli.py`

**Interfaces:**
- Produces :
  - `class ClaudeCliError(Exception)`, avec un message en français prêt à afficher.
  - `@dataclass(frozen=True) class AgentInfo: id: str; uuid: str; cwd: str; status: str; state: str | None`
  - `def parse_backgrounded(output: str) -> str | None` : identifiant court tiré de `backgrounded · <id> · <nom>`.
  - `def parse_agents(output: str) -> list[AgentInfo]` : seulement les entrées `kind == "background"`. Lève `ClaudeCliError` si la sortie n'est pas un tableau JSON.
  - `def session_name(project: str, prompt: str) -> str` : « <Projet> – <prompt> » coupé à 50 caractères (coupure sur un mot si possible, sans espace final).
  - `class ClaudeCli:` `__init__(self, exe: str, run: Runner = _run)` où `Runner = Callable[[list[str], Path | None, float], Awaitable[tuple[int, str]]]` (arguments, dossier, délai : code de retour et sortie fusionnée stdout+stderr).
    - `async def launch(self, cwd: Path, name: str, prompt: str, resume: str | None = None) -> str` : renvoie l'identifiant court. Arguments : nouvelle session `[exe, "--bg", "--permission-mode", "auto", "-n", name, "--", prompt]` ; reprise `[exe, "--bg", "--resume", resume, "--", prompt]`, sans aucune autre option (voir « Résultats de l'essai »). Délai : 30 s.
    - `async def agents(self) -> list[AgentInfo]` : `[exe, "agents", "--json"]`.
    - `async def stop(self, short_id: str) -> None` : `[exe, "stop", short_id]`.
    - `def open_import(self, uuid: str) -> None` : `os.startfile(f"claude://resume?session={uuid}")`. L'UUID est validé par une expression régulière d'UUID avant l'appel ; sinon `ClaudeCliError`.
  - `def find_claude(configured: str | None) -> str | None` : le chemin configuré s'il existe, sinon `shutil.which("claude")`.
- Erreurs de `launch` (toutes en `ClaudeCliError`) : code de retour non nul ; sortie sans identifiant ; « Workspace not trusted » dans la sortie, avec le message « Ouvre une fois Claude Code dans ce dossier pour lui faire confiance. » ; délai dépassé, avec « Claude Code n'a pas répondu à temps. ».

- [ ] **Step 1 : écrire les tests qui échouent**

```python
def test_parse_backgrounded_reads_the_short_id():
    out = "Starting background service…\nbackgrounded · 915c4b6f · Essai Dr Vocal\n  claude agents  list"
    assert parse_backgrounded(out) == "915c4b6f"
    assert parse_backgrounded("Workspace not trusted.") is None

def test_parse_agents_keeps_background_sessions_only():
    out = json.dumps([
        {"pid": 1, "cwd": "D:\\x", "kind": "interactive", "sessionId": "a", "status": "idle"},
        {"pid": 2, "id": "915c4b6f", "cwd": "D:\\NasaCode\\DrVocal", "kind": "background",
         "sessionId": "915c4b6f-4ca1-4d37-9a28-1c471c66c24b", "status": "busy", "state": "working"},
    ])
    assert parse_agents(out) == [AgentInfo("915c4b6f", "915c4b6f-4ca1-4d37-9a28-1c471c66c24b",
                                           "D:\\NasaCode\\DrVocal", "busy", "working")]

def test_parse_agents_rejects_non_json():
    with pytest.raises(ClaudeCliError):
        parse_agents("warning: update available\n")

def test_session_name_is_bounded():
    assert session_name("GeoGame", "corriger le bug du score") == "GeoGame – corriger le bug du score"
    assert len(session_name("GeoGame", "mot " * 40)) <= 50

async def test_launch_passes_the_prompt_as_one_argument():
    calls = []
    async def run(args, cwd, timeout):
        calls.append((args, cwd, timeout)); return 0, "backgrounded · abc123 · x"
    cli = ClaudeCli("claude", run)
    assert await cli.launch(Path("D:/p"), "P – x", '-rf "quoted" prompt') == "abc123"
    args, cwd, timeout = calls[0]
    assert args[:6] == ["claude", "--bg", "--permission-mode", "auto", "-n", "P – x"]
    assert args[-1] == '-rf "quoted" prompt' and cwd == Path("D:/p") and timeout == 30
    assert "bypassPermissions" not in args

async def test_launch_with_resume():  # --resume <uuid> avant le prompt
async def test_launch_untrusted_folder_raises_a_helpful_error():  # message contient "faire confiance"
async def test_launch_nonzero_exit_raises():
async def test_launch_timeout_raises():  # run lève asyncio.TimeoutError -> ClaudeCliError "à temps"
def test_open_import_refuses_a_non_uuid(monkeypatch):  # os.startfile jamais appelé
```

- [ ] Step 2 : `uv run pytest tests/test_claude_cli.py -q`, ÉCHEC (module absent).
- [ ] Step 3 : implémenter `claude_cli.py`. `_run` utilise `asyncio.create_subprocess_exec(*args, cwd=..., stdout=PIPE, stderr=STDOUT, creationflags=CREATE_NO_WINDOW sur win32)` puis `asyncio.wait_for(proc.communicate(), timeout)`. En cas de délai dépassé, tuer le processus avant de relever l'erreur. Décodage en UTF-8 avec `errors="replace"`. Les codes ANSI ne posent pas problème pour `--bg` (sortie non TTY).
- [ ] Step 4 : tests verts, puis ruff et pyright.
- [ ] Step 5 : commit `feat: wrap the claude CLI for background sessions`.

### Task 4: Registre des sessions

**Files:**
- Create: `src/drvocal/claude_registry.py`
- Test: `tests/test_claude_registry.py`

**Interfaces:**
- Produces :
  - `State = Literal["running", "waiting", "done", "stopped", "failed"]`
  - `@dataclass class SessionRecord: id: str; uuid: str; project: str; path: str; name: str; started: datetime; state: State; imported: bool = False; parent: str | None = None`
  - `class Registry:` `__init__(self, path: Path, now: Callable[[], datetime] = datetime.now)` ; `records: list[SessionRecord]` (ordre de lancement) ; `add(rec)`, `save()` (écriture atomique : fichier temporaire puis `os.replace`) ; `latest() -> SessionRecord | None` ; `alive() -> list[SessionRecord]` (état `running` ou `waiting`) ; `to_import() -> list[SessionRecord]` (non importées, état différent de `running`, et pas remplacées par une reprise : on garde la plus récente de chaque chaîne `parent`).
  - Chargement : fichier absent ou JSON invalide, registre vide et `log.warning`. Les sessions `imported` de plus de 7 jours sont purgées au chargement.

- [ ] Step 1 : tests qui échouent : aller-retour `save` puis chargement ; JSON corrompu donne un registre vide et la sauvegarde suivante réécrit le fichier ; purge à 7 jours (`now` injecté : une session importée vieille de 8 jours disparaît, une non importée vieille de 8 jours reste) ; `to_import` exclut `running`, les sessions déjà importées et le parent d'une reprise.
- [ ] Step 2 : ÉCHEC, puis implémentation, puis tests verts, ruff et pyright.
- [ ] Step 3 : commit `feat: remember background Claude sessions across restarts`.

### Task 5: Contrôleur vocal et surveillance

**Files:**
- Create: `src/drvocal/claude_voice.py`
- Test: `tests/test_claude_voice.py`

**Interfaces:**
- Consumes : `ClaudeCli`, `ClaudeCliError`, `AgentInfo`, `session_name` (tâche 3) ; `Registry`, `SessionRecord` (tâche 4).
- Produces : `class ClaudeVoice:`
  - `__init__(self, cli: ClaudeCli, registry: Registry, projects: dict[str, Path], notify: Callable[[str], None], error: Callable[[str], None], play: Callable[[str], None], working: frozenset[tuple[str, str | None]] = WORKING, interval: float = 5.0)`. `notify` ajoute une ligne de texte sur le deuxième écran, `error` une ligne d'erreur. `WORKING` est le couple ou les couples `(status, state)` relevés dans la tâche 1, par défaut `{("busy", "working")}`.
  - `async def prompt(self, project: str, text: str) -> bool`
  - `async def proceed(self, text: str) -> bool`
  - `async def stop(self) -> bool`
  - `def import_all(self) -> bool`
  - `async def poll_once(self) -> None` : une passe de surveillance (testable).
  - `def start(self) -> None` : au démarrage, signale « N sessions Claude à importer » s'il y en a, et lance la boucle si des sessions sont vivantes.
  - La boucle de surveillance (tâche asyncio interne) appelle `poll_once` toutes les `interval` secondes tant que `registry.alive()` n'est pas vide, puis s'arrête. `prompt` et `proceed` la relancent au besoin.
- Règles (de la spec ; les valeurs de retour deviennent `Outcome.ok`) :
  - `prompt` : projet inconnu, échec. Un projet qui a une session `running`, ou un lancement en cours (verrou par projet posé avant l'appel à `launch`), donne un échec et l'erreur « Claude travaille déjà sur <Projet>. ». Ensuite `launch`, puis `agents()` pour trouver l'UUID (même `id`). `SessionRecord(state="running")`, `save`, `notify("<nom> : lancée")`, et la boucle démarre. Une `ClaudeCliError` donne un échec et `error(str(e))`.
  - `proceed` : la cible est `registry.latest()`. Aucune, échec. `imported`, échec et l'erreur « Déjà dans l'app, continue là-bas. ». `running`, échec et l'erreur « Claude travaille encore. ». Si la session est vivante (`waiting`), `stop` d'abord. Puis `launch(..., resume=uuid)`. Si l'identifiant renvoyé est le même, l'enregistrement repasse en `running`. Sinon, nouvel enregistrement avec `parent=<ancien id>`. Si l'UUID ne change pas mais que l'identifiant court change, la même règle s'applique ; le cas réel est figé par la tâche 1.
  - `stop` : la session vivante la plus récente reçoit `cli.stop` et passe en `stopped`, avec `notify("<nom> : arrêtée")`. Aucune : `True` sans rien faire.
  - `poll_once` : `agents()`. Une `ClaudeCliError` donne un `log.warning` et la fonction s'arrête là (pas de bip). Pour chaque enregistrement vivant :
    - absent de la liste : `stopped` ;
    - `(status, state)` dans `working` : rien ;
    - `status == "idle"` : `done`, `play("done")`, `notify("<nom> : finie")`, puis `cli.stop(id)` ;
    - autre état vivant : `waiting`, `play("done")`, `notify("<nom> : attend ta réponse")`, sans arrêter la session.
    Le bip ne joue qu'au changement d'état : une session déjà `waiting` ne rebipe pas. `save` à chaque changement.
  - `import_all` : pour chaque `to_import()`, `cli.open_import(uuid)` puis `imported=True`. Les sessions `running` sont ignorées, avec la ligne « <nom> : encore en cours, à importer plus tard ». `save`. Rien à importer : `True`.

- [ ] **Step 1 : tests qui échouent**, avec un `FakeCli` (listes `launched`, `stopped`, `imported` ; `agents_result` modifiable ; option pour lever `ClaudeCliError`) et `tmp_path` pour le registre :
  - `test_prompt_launches_in_the_project_folder_and_records_it`
  - `test_prompt_unknown_project_fails_without_launching`
  - `test_prompt_refuses_a_second_session_on_a_busy_project`
  - `test_prompt_twice_concurrently_launches_once` (Review Focus 5 : `launch` bloqué sur un `asyncio.Event`, deux `prompt` en `gather`, un seul lancement)
  - `test_prompt_cli_error_is_shown_and_fails`
  - `test_poll_idle_marks_done_beeps_once_and_stops_the_session`
  - `test_poll_waiting_beeps_once_and_keeps_the_session_alive`
  - `test_poll_missing_session_is_stopped_without_beep`
  - `test_poll_bad_agents_output_is_ignored` (Review Focus 2 : aucun bip, état inchangé)
  - `test_proceed_resumes_the_latest_session`
  - `test_proceed_refuses_an_imported_session`
  - `test_proceed_refuses_while_running`
  - `test_proceed_with_new_id_records_a_child`
  - `test_stop_stops_the_latest_alive_session`
  - `test_import_all_opens_each_finished_session_once`
  - `test_start_after_restart_resumes_watch_without_beeping_finished_ones` (Review Focus 4)
- [ ] Step 2 : ÉCHEC, puis implémentation, puis tests verts, ruff et pyright.
- [ ] Step 3 : commit `feat: drive background Claude Code sessions by voice`.

### Task 6: Brancher la voix : intentions, actions, démarrage, réglage

**Files:**
- Modify: `src/drvocal/intent.py` (nouvelle règle `claude.import`), `src/drvocal/actions.py` (`ACTION_NAMES` + `"claude.import"`), `src/drvocal/app.py` (`register_claude`), `src/drvocal/__main__.py` (câblage), `src/drvocal/config.py` (+ `claude_command: str | None = None`), `config.example.toml` (exemple commenté de `claude_command`, et `"GeoGame"` en exemple dans `[projects]`)
- Test: `tests/test_intent.py`, `tests/test_app.py`, `tests/test_config.py`, `tests/test_main.py` si besoin

**Interfaces:**
- Consumes : `ClaudeVoice` (tâche 5), `find_claude`, `ClaudeCli` (tâche 3), `Registry` (tâche 4), `validate_project_root` (tâche 2).
- Produces : `register_claude(catalogue: Catalogue, voice: ClaudeVoice | None) -> None`, qui ne fait rien si `voice is None`. Elle enregistre `claude.prompt` (`voice.prompt(intent.args["project"], intent.args["prompt"])`), `claude.continue`, `claude.stop` et `claude.import`. Les deux premières lancent le travail sans attendre la fin du tour de Claude, mais **attendent** la fin de `launch`, pour que le bip de succès ou d'échec soit le bon.
- Dans `__main__.amain` : `exe = find_claude(settings.claude_command)`. Absent : `log.info("Claude Code introuvable : commandes Claude désactivées")`, puis `voice = None`. Les projets valides passent par `validate_project_root`, comme aujourd'hui. Aucun projet valide : `voice = None`. Sinon `ClaudeVoice(ClaudeCli(exe), Registry(data_dir() / "claude_sessions.json"), projets, notify=…, error=…, play=player.play)`, puis `voice.start()`. `notify` et `error` poussent sur le deuxième écran (`push(SessionEvent("text", …))` et `SessionEvent("error", …)`).

- [ ] **Step 1 : tests qui échouent**
  - `test_intent.py` : « importe mes sessions Claude », « importe les sessions claude », « importe Claude », « ouvre mes sessions Claude » donnent `Intent("claude.import", {})` ; « importe ce titre dans ma playlist X » ne donne pas `claude.import`.
  - `test_app.py` : `register_claude(catalogue, None)` n'enregistre rien ; avec un `ClaudeVoice` factice, les quatre actions appellent la bonne méthode et `Outcome.ok` reflète son retour.
  - `test_config.py` : `claude_command` lu, `None` par défaut.
- [ ] Step 2 : ÉCHEC, puis implémentation, puis tests verts.
- [ ] Step 3 : dans le câblage, l'ancien `ClaudeRunner` n'est plus construit et `register_claude` utilise la nouvelle signature. Les anciens modules restent présents mais inutilisés (supprimés à la tâche 7).
- [ ] Step 4 : ruff, pyright et la suite complète au vert. Commit `feat: launch and import Claude Code sessions by voice`.

### Task 7: Supprimer l'ancien Claude Agent et nettoyer l'écran

**Files:**
- Delete: `src/drvocal/claude_session.py`, `src/drvocal/claude_policy.py`, `src/drvocal/claude_audit.py`, `tests/test_claude_session.py`, `tests/test_claude_policy.py`, `tools/spike_claude.py`
- Create: `src/drvocal/events.py` avec `@dataclass(frozen=True) class SessionEvent: kind: str; text: str` (kinds `text`, `done` et `error`)
- Modify:
  - `src/drvocal/screen.py` et `screen.html` : retirer `pending`, `parse_pending`, `_Bridge.decide`, `on_decision`, `Reply`, les boutons et leurs styles ; la règle d'éviction ne protège plus rien.
  - `src/drvocal/app.py` : retirer `make_ask_user`, `make_event_handler` (et `parse_reply`) s'il n'a plus d'appelant.
  - `src/drvocal/__main__.py` : retirer `claude_api_key`, `screen.on_decision` ; `"claude_api_key"` sort de `SECRET_NAMES`.
  - `pyproject.toml` et `uv.lock` : `uv remove claude-agent-sdk`.
  - `README.md` : réécrire la partie Claude (voir Step 2).
  - `tests/test_screen.py`, `tests/test_secrets_store.py`, `tests/test_main.py`, `tests/test_actions.py` : retirer ce qui teste l'ancien fonctionnement.

- [ ] Step 1 : supprimer et déplacer. `grep -rn "claude_session\|claude_policy\|claude_audit\|claude_agent_sdk\|ANTHROPIC_API_KEY\|claude_api_key\|pending" src tests tools` ne doit plus rien renvoyer d'utile (hors les « pending » sans rapport, à vérifier à la main).
- [ ] Step 2 : README.
  - **Présentation** (ligne 12) : « **Claude Code** (facultatif) : un prompt dicté lance une session Claude Code en arrière-plan, sur ton abonnement, dans le dossier d'un projet que tu nommes ; « importe mes sessions Claude » les ouvre ensuite dans l'app Claude. »
  - **Prérequis** : à la place de la clé API, Claude Code installé et connecté (`claude` dans le PATH, sinon `claude_command`), et chaque projet ouvert une fois dans Claude Code pour qu'il soit de confiance.
  - **Section commandes** : ajouter « importe mes sessions Claude ».
  - **« Deuxième écran et sessions Claude »** : mode auto, une session à la fois par projet, bip « Claude a fini » (aussi quand Claude attend ta réponse), import à la demande seulement (il ouvre l'app), on ne continue pas à la voix une session déjà importée. Claude Code travaille dans son propre worktree (branche `worktree-<nom>`) : les changements se retrouvent dans la session importée, pas directement dans la copie de travail.
  - **À supprimer** : clé API, limites (30 tours, 2 dollars, 15 minutes), politique d'autorisations, « Répondre à Claude ».
  - **Journal des commandes** : la phrase sur les réponses à Claude disparaît.
- [ ] Step 3 : `uv sync`, puis ruff, pyright et pytest au vert.
- [ ] Step 4 : commit `refactor: remove the API-key Claude Agent and its voice approvals`.

### Task 8: Essai réel (session principale)

- [ ] Ajouter `"GeoGame" = "D:/NasaCode/GeoGame"` dans `%APPDATA%\DrVocal\config.toml`, après accord de l'utilisateur, puis relancer Dr Vocal.
- [ ] Faire dire à l'utilisateur « salut doc vocal, demande à Claude sur Dr Vocal de lister les fichiers du dossier docs sans rien modifier ». Attendus : bip de succès, ligne « lancée » à l'écran, puis bip « fini ».
- [ ] « Importe mes sessions Claude » : la session apparaît dans l'app avec sa réponse.
- [ ] Lire `drvocal.log` : aucune erreur.

## Résultats de l'essai (tâche 1)

Relevé le 2026-11-09 avec `claude` 2.1.286. Ces valeurs priment sur le texte des tâches.

- **`claude agents --json`** (sessions actives seulement ; `--all` ajoute celles qui sont terminées) :
  - en travail : `status="busy"`, `state="working"` ; donc `WORKING = {("busy", "working")}` ;
  - tour fini : `status="idle"`, `state="done"` ;
  - bloquée sur une autorisation : `status="waiting"`, `state="blocked"`, avec en plus `waitingFor="permission prompt"` ;
  - arrêtée : absente sans `--all`.
- **`--`** est accepté avant le prompt : `claude --bg … -n <nom> -- "<prompt>"`.
- **Ligne de lancement** : `backgrounded · <id>` ou `backgrounded · <id> · <nom>`. Le nom est facultatif, et Claude Code peut retitrer la session.
- **Reprise** : `claude --bg --resume <UUID> -- "<prompt>"` **sans aucune autre option** garde le même identifiant et réutilise les options enregistrées (`--permission-mode auto` compris). Avec une option en plus (`--permission-mode` par exemple), la CLI crée une **copie** sous un nouvel identifiant. Donc `launch(..., resume=uuid)` ne passe ni `--permission-mode` ni `-n`.
- **Import** : `claude://resume?session=<UUID>` importe aussi une session arrêtée ; elle apparaît dans l'app sous son nom.
- **Worktree** : avant d'écrire, une session d'arrière-plan se crée **d'elle-même** un worktree `.claude/worktrees/<nom>`, sur une branche `worktree-<nom>`. Les modifications de Claude n'arrivent donc pas directement dans la copie de travail du projet. On le retrouve dans l'app, comme pour les autres sessions.
- `claude rm <id>` supprime l'état de la session et son worktree.
