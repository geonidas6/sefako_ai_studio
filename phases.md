Dans l’état actuel du projet, ces deux boutons ne font pas la même chose.

**`Lancer la conception technique`**
- Appelle `POST /projects/{id}/technical-design/start`.
- Il faut être admin.
- Si la validation admin est requise, il demande confirmation avant de continuer.
- Il crée le workspace technique du projet et initialise surtout les fichiers de cadrage:
  - `README.md`
  - `docs/cdc.md`
  - `docs/mcd.md`
  - `docs/architecture.md`
  - `docs/roadmap.md`
  - `docs/notes_synthese.md`
  - `docs/stack_decision.md`
  - `docs/implementation_plan.md`
  - `docs/requirements_matrix.md`
  - `docs/editor_handoff.md`
  - `.aia/workspace-policy.json`
- En gros, ce bouton prépare le dossier de travail et la documentation de référence.
- Il ne lance pas encore la génération du code source final.

**`Lancer la phase applicative`**
- Appelle `POST /projects/{id}/implementation/start`.
- Il faut aussi être admin.
- Il ne fonctionne que si la conception technique a déjà été initialisée.
- Il démarre la phase applicative, c’est-à-dire le pipeline qui:
  - prépare le workspace technique du projet,
  - transmet le contexte Markdown,
  - ouvre l'éditeur web sur le dossier du projet,
  - et laisse l'équipe travailler directement dans le workspace.
- Dans votre configuration actuelle, les agents du studio produisent les documents Markdown puis le code se fait dans l'éditeur web.

**Résumé simple**
- `Conception technique` = créer la base documentaire et le workspace du projet.
- `Phase applicative` = passer au travail réel dans l'éditeur web sur le dossier du projet.

Si tu veux, je peux aussi te faire un petit schéma “bouton -> endpoint -> effet réel” pour les deux.
