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

## Limites
- La détection se base sur le **volume** (pas sur le sens) : un bruit fort sera gardé comme de la parole.
- Le script n'a pas pu être testé dans Resolve 21 lui-même ici ; l'analyse des silences, elle, est testée.
  Si un point de l'API diffère chez toi, le message d'erreur dans la console de Resolve (Espace de travail > Console) me permettra de l'ajuster.
