# Raccourcis simules et anti-triche

Question : est-ce risque de faire envoyer par Dr Vocal une combinaison de touches
(ex. `ctrl+shift+m`) via `SendInput` pour couper le micro Discord pendant qu'un jeu
est au premier plan ?

Resume : **le risque n'est pas ecarte.** Les sources primaires consultees sont soit
inaccessibles (corps de page vide), soit muettes sur ce cas precis. Aucune ne dit que
c'est sans danger. La fonctionnalite reste donc desactivee par defaut
(`simulated_hotkeys_enabled = false`) ; c'est a l'utilisateur de decider apres lecture.

Date de la recherche : 2026-11-02. Methode : lecture des pages via un outil de fetch
(qui renvoie parfois uniquement le menu des pages Steam/Epic) et recherche web.

## Faits (ce que les sources disent)

### Counter-Strike 2 / VAC (Valve)

- Fair Play Guidelines de CS2, https://blog.counter-strike.net/index.php/fair-play-guidelines/ :
  la regle "In all modes" dit : "Never use any automation for any reason." Les sanctions
  possibles : cooldowns, restrictions de communication, Game Bans. La page ne mentionne
  ni macros ni logiciels tiers. (Lue directement.)
- Citation identique rapportee par un message du forum Steam,
  https://steamcommunity.com/app/730/discussions/0/3544924290432032768 (source secondaire).
- Presse (PC Gamer, Dexerto, KitGuru) : en aout 2024 Valve a interdit sur les serveurs
  officiels les modes clavier type Snap Tap (SOCD) et les automatisations d'entree
  (ex. jump-throw bind), avec des kicks "input automation" parfois errones. Titre PC Gamer :
  https://pcgamer.com/games/fps/valve-says-weve-decided-to-draw-a-clear-line-and-bans-snap-tap-keyboard-automation-from-counter-strike-2
  (corps non lu ; la presse est secondaire, la declaration de Valve elle-meme n'a pas pu
  etre lue).

### VAC (Steam Support)

- Pages https://help.steampowered.com/en/faqs/view/571A-97DA-70E9-FF74 et
  https://help.steampowered.com/en/faqs/view/647C-5CC1-7EA9-3E0F : le fetch n'a renvoye que
  le titre ("Valve Anti-Cheat (VAC) System") et la navigation, **corps absent**. Je n'ai donc
  rien de verifiable sur ce que VAC dit des entrees simulees.

### Rocket League (Psyonix / Epic, Easy Anti-Cheat)

- Presse (PC Gamer, TechRadar, Insider Gaming) : EAC active sur PC a partir du 28 avril
  (annee rapportee par les sources : 2026), lancement avec ou sans EAC possible ; sans EAC,
  les mods fonctionnent hors ligne ; avec EAC, BakkesMod et la plupart des plugins tiers ne
  tournent pas. Un article indique que les overlays tiers sont restreints.
  Ex. https://www.pcgamer.com/games/sim/easy-anti-cheat-is-coming-to-rocket-league-but-psyonix-promises-not-to-get-all-fortnite-with-it-and-hose-your-steam-deck-and-linux-installs/
- Pages d'aide Epic (https://www.epicgames.com/help/c-202300000001622/c-202300000001679/how-to-enable-easy-anti-cheat-for-rocket-league-a202300000084282) :
  **HTTP 403, non lues.**
- Aucun resultat ne parle de macros, de remappage ou de logiciels de peripheriques.

### Red Dead Redemption 2 (Rockstar)

- Presse (PC Gamer, KitGuru, Prima Games) : Rockstar tolere les mods solo non commerciaux
  mais interdit le modding en ligne ; sanctions rapportees pour Red Dead Online (suspension
  30 jours, reset). Rien sur macros ou entrees simulees. Pages de support Rockstar non lues.
  Ex. https://pcgamer.com/red-dead-redemption-2-mods-are-probably-okay-as-long-as-you-stay-offline

### Cyberpunk 2077 (CD Projekt Red)

- Aucune declaration CDPR sur un anti-cheat trouvee. Corsair mentionne de facon generale que
  macros et touches multi-actions ont deja pose probleme avec des anti-cheat
  (https://corsair.com/explorer/gamer/accessories/icue-and-anti-cheat-programs-explained :
  URL renvoyee en 404 au fetch, donc seulement le resume du moteur de recherche).

## Inferences (non verifiees par une source primaire)

- Cyberpunk 2077 est un jeu solo sans mode multijoueur (connaissance generale, non
  confirmee par les pages consultees) : pas d'anti-cheat en ligne attendu.
- Les anti-cheat comme VAC/EAC se concentrent en pratique sur l'injection dans le processus
  du jeu et sur les modes de triche ; une application tierce qui envoie une combinaison via
  `SendInput` globale ne touche pas le processus du jeu. C'est une hypothese plausible,
  **pas une garantie**.
- `SendInput` marque les evenements comme injectes (drapeau `LLKHF_INJECTED` pour les hooks
  bas niveau) : un jeu ou un anti-cheat peut techniquement les distinguer du materiel.
  Connaissance technique Windows, non liee a une politique d'editeur.
- Le risque principal est le cas CS2 : la regle "Never use any automation" est large, et
  la presse rapporte des faux positifs. Une combinaison unique declenchee par la voix est
  tres differente d'un macro de jeu, mais les sources ne le disent pas.
- Si le jeu est au premier plan, il recoit aussi les touches simulees (pas seulement
  Discord) : effet de bord possible en jeu, independamment de l'anti-cheat.

## Inconnu

- Le texte du corps des pages VAC de Steam Support et de la declaration de Valve d'aout 2024.
- Les pages d'aide Epic/Psyonix sur EAC et les logiciels tiers.
- Les politiques Rockstar sur les logiciels tiers/macros pour RDR2 et RDO.
- Si une touche unique envoyee par `SendInput` a un jeu au premier plan a deja entraine un ban,
  pour VAC, EAC ou Rockstar.

## Decision

Rien n'est declare sur. Option la plus prudente : garder
`simulated_hotkeys_enabled = false` (defaut), ou n'activer que hors ligne / hors jeux a
anti-cheat (CS2, Rocket League en ligne, RDO). Tout test reel (etape 6 du plan) reste a la
decision de l'utilisateur apres lecture de ce document ; lire les pages ci-dessus dans un
navigateur est recommande.

## Mode touche a maintenir

Le mode de reveil `key` lit passivement l'etat d'une touche ou d'un bouton de souris
(`GetAsyncKeyState`, lecture seule). Rien n'est envoye au jeu, aucun hook clavier ni souris
n'est installe, aucune entree n'est simulee : le jeu recoit la touche normalement. Choisir
une touche non utilisee en jeu pour eviter un effet de bord.

