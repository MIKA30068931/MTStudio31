# Agent de dérushage pour DaVinci Resolve 21

Un script qui, en un clic :
1. lit ton dossier **Montage vidéo** (un sous-dossier = une catégorie de rushs) ;
2. crée un **projet Resolve** avec des bins `Rushs/<catégorie>` et importe tout ;
3. **supprime les silences** sans toucher aux dialogues (marges avant/après) ;
4. crée une timeline **« <catégorie> - Dérushé »** par catégorie + une **timeline globale**.

## Organisation attendue
```
Montage vidéo/
├── Interview/      entretien1.mp4 ...   -> dérushé (silences retirés)
├── Plateau/        ...                  -> dérushé
└── B-roll/         ...                  -> gardé entier (liste modifiable)
```

## Installation
1. Installer Python 3 et **ffmpeg** (dans le PATH).
2. Resolve : Préférences > Système > Général > **Scripts externes = Local**.
3. Copier `derush_agent.py` et `config.json` dans le dossier Scripts de Resolve :
   - Windows : `%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Utility`
   - macOS : `~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility`
   - Linux : `~/.local/share/DaVinciResolve/Fusion/Scripts/Utility`

## Utilisation
- **Dans Resolve** : Espace de travail > Scripts > `derush_agent` (une fenêtre te demande le dossier).
- **Depuis un terminal** (Resolve Studio ouvert) : `python derush_agent.py "D:/Montage vidéo"`
- **Tester sans Resolve** : ajouter `--analyse-seule` -> écrit `rapport_derush.json` avec les coupes.

Réglages en ligne de commande : `--seuil -35` (plus bas = plus sensible), `--silence-min 0.8`.

## Réglages (`config.json`)
| Clé | Rôle |
|---|---|
| `seuil_silence_db` | Niveau sous lequel c'est du silence (-32 dB). Baisse-le (-40) si du bruit de fond reste. |
| `duree_silence_min_s` | Silence minimum supprimé (0,6 s). Les petites pauses naturelles sont conservées. |
| `marge_avant_s` / `marge_apres_s` | Respiration gardée avant/après la parole (0,15 / 0,25 s). |
| `segment_min_s` | Ignore les bruits très brefs (0,4 s). |
| `sous_dossiers_sans_derush` | Catégories gardées entières (B-roll, ambiance...). |

## Marqueurs de couleur sur les clips
Chaque clip de la timeline reçoit un marqueur (nom + note visibles en double-cliquant dessus) :

| Couleur | Sens |
|---|---|
| 🔵 Bleu | Passage dérushé ; la note indique le silence supprimé avant et la plage source. |
| 🟡 Jaune | **Grosse coupe** (silence ≥ 3 s retiré juste avant) : à vérifier en priorité. |
| 🟣 Violet | Clip gardé entier (B-roll, ambiance, clip sans audio). |
| 🟢 Vert | Illustration sur V2 : requête, texte dit à ce moment et crédit de l'image. |

Réglages dans `config.json` : `"marqueurs": false` pour désactiver, `marqueur_coupe_longue_s` pour le seuil du jaune.
Astuce : Timeline > Marqueurs permet de filtrer par couleur et de sauter d'un jaune à l'autre.

## Illustrations automatiques (`--illustrations`)
L'agent écoute le dialogue, cherche sur internet des images/vidéos qui illustrent le propos et les pose
sur la **piste V2**, calées sur le moment où la phrase est dite (même après suppression des silences).

```
python derush_agent.py "D:/Montage vidéo" --illustrations
```
1. **Transcription locale** (Whisper) : `pip install faster-whisper` - l'audio ne quitte pas ton PC.
2. **Requêtes visuelles** : avec `ANTHROPIC_API_KEY`, Claude écrit une requête concrète en anglais par
   passage (ex. « construite en 1889 à Paris » -> `eiffel tower construction`). Sans clé : mots-clés
   simples, nettement moins pertinents.
3. **Recherche** (dans l'ordre) : Pexels et Pixabay (vidéos puis photos, clés gratuites
   `PEXELS_API_KEY` / `PIXABAY_API_KEY`), puis Wikimedia Commons (sans clé, photos).
4. Les photos deviennent des clips avec léger zoom ; tout est rangé dans `Montage vidéo/Illustrations/`
   (bin « Illustrations » dans Resolve) avec les crédits dans `CREDITS.json`.
5. Seules les catégories dérushées sont illustrées (pas B-roll/Ambiance).

**À savoir**
- **Confidentialité** : le texte du dialogue est envoyé aux sites de recherche (et à Claude si la clé est
  définie). Ne l'active pas sur du contenu confidentiel.
- **Droits** : Pexels/Pixabay sont libres d'usage ; Wikimedia exige souvent une **attribution** (voir
  `CREDITS.json`). Vérifie toujours la licence avant publication.
- Les illustrations sont des **propositions** : relis la V2 et supprime celles qui ne collent pas.
- Un bloc qui chevauche une coupe est raccourci au passage conservé.
- Les marqueurs sont posés sur la V1 seulement si le nombre de clips correspond aux coupes prévues (sinon un avertissement s'affiche).
- Cette partie est testée avec une transcription et une recherche simulées (pas d'accès internet ici) :
  la recherche réelle et Whisper restent à valider sur ta machine.

## Limites
- La détection se base sur le **volume** (pas sur le sens) : un bruit fort sera gardé comme de la parole.
- Le script n'a pas pu être testé dans Resolve 21 lui-même ici ; l'analyse des silences, elle, est testée.
  Si un point de l'API diffère chez toi, le message d'erreur dans la console de Resolve (Espace de travail > Console) me permettra de l'ajuster.
