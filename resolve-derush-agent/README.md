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

## Resolve gratuit 21.1 : mode export (sans scripting)
D'après les informations trouvées (non confirmées par les pages officielles, illisibles depuis ma session),
le scripting est réservé à **DaVinci Resolve Studio** depuis la 21.1 ; la version gratuite n'a plus de menu
Scripts pour Python. Pour ce cas, l'agent travaille **en dehors de Resolve** et livre des fichiers à importer :
```
py -3 derush_agent.py "D:\Montage vidéo" --export --sous-titres --habillage
```
(ajoute `--illustrations` et/ou `--musique "calme"` si tu veux). Résultat dans `Montage vidéo/` :
- `Export Resolve/<nom>.fcpxml` : une timeline par catégorie + une globale, silences retirés, avec
  V1 = passages conservés, V2 = illustrations, V3 = bandeaux et titres, A2 = musique (timeline globale) ;
- `Sous-titres/*.srt`, `Illustrations/`, `Habillage/`, `Musique/_rendus/` et les fichiers de crédits.

**Dans Resolve :** Fichier > Importer > Timeline... > choisis le `.fcpxml`. Si Resolve demande de lier les médias,
indique ton dossier Montage vidéo. Sous-titres : ouvre la timeline, puis Fichier > Importer > Sous-titres...
Si tu lances la commande sans `--export` et que Resolve ne répond pas aux scripts, l'agent bascule tout seul en mode export.

Limites : le fichier FCPXML n'a pas pu être testé dans Resolve ici (seule sa structure est vérifiée) ; les couleurs
des marqueurs ne passent pas par ce format (seules les « grosses coupes » sont marquées) ; la musique est attachée
à la timeline globale uniquement.

## Installation rapide
- **Windows** : double-clic sur `installer_windows.bat` (installe Python, ffmpeg, Whisper et copie les scripts dans Resolve).
- **macOS / Linux** : `bash installer_mac_linux.sh`.
- Vérification à tout moment : `python verifier_installation.py`.
- Le modèle Whisper (~500 Mo pour « small ») se télécharge tout seul au premier usage des illustrations.

## Installation manuelle
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

## Bandeaux de nom et titres de sections (`--habillage`)
```
python derush_agent.py "D:/Montage vidéo" --habillage
```
- **Titre de section** : au début de chaque catégorie dérushée (fondu + léger glissement + trait d'accent), 3,5 s.
- **Bandeau de nom** (nom + fonction) : à chaque interview, qui glisse depuis la gauche et ressort, 5 s, dans le premier passage assez long du clip et sans chevaucher le titre.
- Les graphiques sont des **clips animés avec transparence** (.mov ProRes 4444) rendus par ffmpeg dans `Montage vidéo/Habillage/`, importés dans le bin « Habillage » et posés sur la **piste V3**, avec marqueurs cyan (bandeau) et lavande (titre).

**Tu remplis un seul fichier : `habillage.json`** (créé automatiquement dans ton dossier Montage vidéo au premier lancement) :
```json
{"intervenants": {"Interview/entretien1": {"nom": "Marie Dupont", "fonction": "Directrice"}},
 "sections": {"Interview": "Les témoignages"}}
```
- `nom` vide = pas de bandeau. L'agent **n'affiche jamais un nom deviné** : si une clé Anthropic est définie, il écrit au mieux une `_suggestion` (nom dit dans l'interview) que tu recopies après vérification.
- `sections` : texte du titre ; vide = pas de titre pour cette catégorie.
- Sans nom rempli, tu obtiens déjà les titres de sections ; remplis les noms puis relance.

**Style** (`config.json`) : `habillage_couleur_accent` (#F5A623), `habillage_couleur_fond` (#101820), `habillage_police` (fichier .ttf ; sinon police système en gras), `habillage_duree_bandeau_s`, `habillage_delai_bandeau_s`, `habillage_duree_titre_s`.
Limites : le texte n'est pas modifiable dans Resolve (corrige `habillage.json` et relance) ; chaque graphique pèse 8 à 15 Mo et demande quelques secondes de rendu ; la police par défaut est une police système, indique la tienne pour respecter ta charte.

## Sous-titres français (`--sous-titres`)
```
python derush_agent.py "D:/Montage vidéo" --sous-titres
```
1. **Transcription locale** (Whisper) avec l'horodatage de **chaque mot** : un seul passage sert aussi aux illustrations.
2. Seuls les mots des **passages conservés** sont gardés, et leurs temps sont recalés sur la timeline (silences retirés) : les sous-titres collent au montage.
3. **Découpage lisible** : 2 lignes de 38 caractères maximum, coupure aux fins de phrases, aux vraies pauses et aux changements de plan, 1 s mini et 6 s maxi par sous-titre.
4. **Typographie française** : espace insécable avant `? ! ; :` et aux guillemets.
5. Un fichier `.srt` par catégorie + `global.srt` dans `Montage vidéo/Sous-titres/`, importés dans le bin « Sous-titres » et posés sur la piste de sous-titres de chaque timeline.

Fonctionne aussi avec `--analyse-seule` (sans Resolve) : tu récupères les `.srt`, utilisables dans n'importe quel logiciel.
Noms propres mal transcrits ? Ajoute-les dans `config.json` : `"vocabulaire": ["Mika", "MTStudio"]`.
Réglages : `sous_titres_max_car_ligne`, `sous_titres_max_lignes`, `sous_titres_duree_min_s`, `sous_titres_duree_max_s`.

Limites : Whisper se trompe parfois (accents, noms propres, chiffres) : **relis les sous-titres**. La pose automatique sur la piste de sous-titres n'a pas été testée dans Resolve 21 ; si elle n'est pas confirmée, l'agent le dit et tu glisses le `.srt` du bin sur la timeline. Le style (police, taille, couleur) se règle dans Resolve (Inspecteur, sous-titres).

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

## Musique de fond à la demande (`--musique`)
```
python derush_agent.py "D:/Montage vidéo" --musique "calme, inspirant"
python derush_agent.py "D:/Montage vidéo" --musique auto          # ambiance déduite du dialogue
python derush_agent.py "D:/Montage vidéo" --musique "énergique" --musique-choisir   # tu choisis la piste
```
La musique est posée sur la piste **A2** de la timeline globale (marqueur 🌸 rose avec titre et crédit).

**Sources, dans l'ordre :**
1. **Tes pistes** dans `Montage vidéo/Musique/` : c'est ici que tu mets les morceaux **téléchargés avec ton
   abonnement Epidemic Sound**. Range-les par ambiance (`Musique/calme/`, `Musique/dynamique/`) : les noms de
   dossiers et de fichiers servent à choisir.
2. **Jamendo** (musique Creative Commons, clé gratuite `JAMENDO_CLIENT_ID`) : les licences non commerciales sont écartées.
3. **Openverse** (sans clé) : licences libres autorisant l'usage commercial.

> **Epidemic Sound** n'offre pas d'API publique de téléchargement : l'agent ne peut donc pas parcourir ni
> télécharger leur bibliothèque. L'offre gratuite et l'affiliation ne donnent pas de musique libre (l'affiliation
> sert à toucher une commission) et la licence est liée à ton abonnement et à tes chaînes. D'où le dossier `Musique/`.

**Rendu automatique (pratiques de post-production) :**
- niveau normalisé (-26 LUFS) pour rester sous la voix ;
- **ducking** : la musique baisse automatiquement quand quelqu'un parle et remonte sur les plans muets (B-roll) ;
- fondu d'entrée (1,5 s) et de sortie (3 s) ; piste bouclée ou coupée à la durée exacte du montage.
Réglages : `musique_lufs`, `musique_ducking`, `musique_ducking_ratio`, `musique_fade_in_s`, `musique_fade_out_s`.

Le mixage est un fichier `Musique/_rendus/musique_mixee.wav` ; les crédits sont dans `CREDITS_MUSIQUE.json`.
Limites : la boucle d'une piste courte n'a pas de fondu enchaîné au raccord ; le mix est calé sur le montage
au moment de l'exécution (si tu retouches la timeline, relance ou ajuste la A2 à la main).

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
