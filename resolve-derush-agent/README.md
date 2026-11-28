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

## Montage complet en un appel (`monter.bat` ou `--tout`)
**Double-clique sur `monter.bat`** (ou glisse ton dossier « Montage vidéo » dessus) : l'agent fait tout seul le montage complet.
Équivalent en ligne de commande : `py -3 derush_agent.py "C:\montage video" --tout`.

Ce que fait `--tout` :
1. **Silences** retirés (seuil automatique).
2. **Hésitations** (« euh », « hum »…) retirées, d'après la transcription Whisper mot par mot.
3. **Prises répétées** : si une phrase est redite presque à l'identique dans les 30 s, on garde la dernière version.
   Chaque phrase retirée est affichée avec son instant, pour vérification.
4. **Sous-titres** français (.srt), **bandeaux de nom et titres** (d'après `habillage.json`), **logos** des marques citées
   (si le dossier `Logos` contient des logos) et **musique** avec J-cut et L-cut (si le dossier `Musique` contient des pistes).
5. Il te demande le **format** (16:9 / 9:16) et la **qualité** (1080p / 4K), puis ouvre le dossier du fichier créé.

Il te reste à **importer dans Resolve** (la version gratuite 21.1 ne permet pas de le faire par script) :
Fichier > Importer > Timeline (le `.fcpxml`), puis Fichier > Importer > Sous-titres (`global.srt`).

Réglages (`config.json`) : `hesitations` (mots retirés), `retirer_hesitations`, `retirer_repetitions`,
`repetition_similarite` (0,85 ; plus bas = retire plus de répétitions), `repetition_fenetre_s` (30).
Séparément : `--nettoyer` (hésitations et répétitions seules).

Limites : un clip prend plusieurs minutes (transcription sur processeur) ; Whisper omet parfois les « euh » (l'agent l'incite
à les transcrire, sans garantie) ; l'agent ne juge pas l'utilité du contenu (il ne retire que silences, hésitations et prises
répétées) ; ce nettoyage n'a pas encore été éprouvé sur de vraies voix : **écoute le résultat** et ajuste.

## Format et qualité : l'agent te pose la question
Au lancement, l'agent demande :
```
Format du montage :   1) 16:9 - horizontal (YouTube, TV, site web)   2) 9:16 - vertical (TikTok, Reels, Shorts)
Qualité du montage :  1) 1080p - Full HD                              2) 4K - Ultra HD
```
Entrée = choix 1. Résultat : 1920x1080, 3840x2160, 1080x1920 ou 2160x3840.
- **Sauter les questions** : `--format 9:16 --resolution 4k`, ou `--sans-questions` (16:9 / 1080p), ou renseigne
  `format_video` et `resolution_video` dans `config.json` (et `"demander_format": false`).
- **Ce qui s'adapte** : la timeline exportée (taille du projet), les bandeaux, titres et logos (rendus à la bonne taille,
  textes longs mis à la ligne ou réduits, bandeau remonté en vertical pour éviter l'interface des réseaux), les images
  d'illustration (converties au bon format) et les sous-titres (lignes de 26 caractères en vertical).
- **Plans d'une autre proportion** (un plan 16:9 dans un montage 9:16) : ils sont réglés pour **remplir l'écran, recadrés
  au centre**. Si la personne n'est pas au centre, il faut recadrer à la main dans Resolve (Inspecteur, Position).
- Limite : le recadrage automatique intelligent (suivre le visage) n'est pas fait.

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

## Seuil de silence automatique (par défaut)
L'agent règle **lui-même** le seuil de silence, clip par clip : il mesure le niveau de crête toutes les 50 ms, cherche la
frontière naturelle entre le bruit de fond et la voix (méthode d'Otsu), puis ajoute 2 dB de marge. Il s'adapte ainsi à une
voix forte, à une voix faible ou à un bruit de fond, sans que tu aies à régler quoi que ce soit. L'idée de mesurer le volume
pour régler le seuil vient des instructions de Remotion ; la méthode de séparation est la mienne.
- Le seuil choisi est affiché pour chaque clip (« seuil auto -46 dB »).
- Un clip muet (aucun signal) est gardé entier, avec un message.
- Pour imposer un seuil : `--seuil -45` (respecté tel quel). Pour revenir à l'automatique : `--seuil auto`.
- Réglages : `seuil_auto` (true/false), `seuil_auto_marge_db` (2 ; plus haut = coupe plus de pauses).
- Testé sur 4 cas synthétiques (voix forte, voix très faible, bruit de fond, voix faible avec bruit) : chacun retire bien
  les 4,2 s de silence prévues. Pas encore éprouvé sur de vraies voix : vérifie les marqueurs jaunes au premier essai.

## Réglages (`config.json`)
| Clé | Rôle |
|---|---|
| `seuil_silence_db` | Seuil fixe (-32 dB), utilisé seulement si `seuil_auto` est désactivé ou si la mesure est impossible. |
| `duree_silence_min_s` | Silence minimum supprimé (0,6 s). Les petites pauses naturelles sont conservées. |
| `marge_avant_s` / `marge_apres_s` | Respiration gardée avant/après la parole (0,15 / 0,25 s). |
| `segment_min_s` | Ignore les bruits très brefs (0,4 s). |
| `sous_dossiers_sans_derush` | Catégories gardées entières (B-roll, ambiance...). |

## Logos animés (`--logos`)
Quand tu cites une marque, son logo apparaît (rebond d'entrée, léger flottement, sortie en fondu) :
```
py -3 derush_agent.py "D:\Montage vidéo" --export --logos
```
1. Au premier lancement, l'agent crée `Montage vidéo/Logos/`. **Dépose-y les logos** (PNG à fond transparent de préférence ; aussi webp, jpg, svg), pris sur la **page officielle ou le kit presse** de la marque : l'agent ne télécharge aucun logo.
2. **Le nom du fichier = la marque** : `ElevenLabs.png`, `Notion.png`...
3. L'agent écoute le dialogue (Whisper, mot par mot) et repère les mentions, y compris en plusieurs mots (« Eleven Labs ») et avec de petites variantes d'orthographe. Les noms des logos sont aussi donnés à Whisper pour qu'il les écrive correctement (sous-titres compris).
4. Variantes mal transcrites ? Ajoute-les dans `Logos/logos.json` : `{"ElevenLabs": ["eleven labs", "11 labs"]}`.
5. Le logo dure 3 s, au moment où la marque est dite (dans un passage conservé), en haut à droite ; une marque ne revient pas avant 30 s. Il est posé sur la **piste V4** (marqueur fuchsia dans Resolve Studio).

Réglages (`config.json`) : `logo_duree_s`, `logo_taille` (part de la largeur, 0,16), `logo_position` (`haut-droite`, `haut-gauche`, `bas-droite`, `bas-gauche`, `centre`), `logo_repetition_min_s`.
Limites : les logos sont animés par un effet commun (pas une animation propre à chaque marque) ; un logo blanc sur fond clair sera peu visible ; vérifie que tu as le droit d'utiliser le logo (usage éditorial pour parler de la marque en général, accord de la marque pour un usage commercial ou sponsorisé).

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

**Musique par séquence avec J-cut et L-cut (par défaut) :** chaque catégorie de rushs est une séquence avec sa musique.
- **J-cut** : la musique de la séquence suivante démarre **avant** le changement d'image (1,5 s par défaut).
- **L-cut** : quand une musique se termine, elle **continue un peu** sur les paroles de la séquence suivante (2,5 s) en
  s'estompant sous la voix.
- Aux jonctions, les deux musiques se **chevauchent en fondu enchaîné** : elles sont posées en alternance sur **A2 et A3**.
- Chaque extrait est baissé uniquement sous la voix de **sa** fenêtre. Si plusieurs pistes ont été trouvées, chaque séquence
  prend une piste différente ; sinon la même continue là où elle s'était arrêtée.
- Réglages (`config.json`) : `musique_j_cut_s`, `musique_l_cut_s`, `musique_categories` (liste de catégories qui
  reçoivent de la musique ; vide = toutes), `musique_section_min_s` (séquences plus courtes ignorées),
  `musique_sections: false` pour revenir à une seule nappe continue.

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

## Dépannage : erreur `open() got an unexpected keyword argument 'metadata_errors'`
La transcription (sous-titres, logos, illustrations) plante avec cette erreur : la bibliothèque `av` installée est trop
récente (19.x) pour `faster-whisper`. Correction : `py -3 -m pip install "av==16.1.0"`, puis relancer la commande.

## Limites
- La détection se base sur le **volume** (pas sur le sens) : un bruit fort sera gardé comme de la parole.
- Le script n'a pas pu être testé dans Resolve 21 lui-même ici ; l'analyse des silences, elle, est testée.
  Si un point de l'API diffère chez toi, le message d'erreur dans la console de Resolve (Espace de travail > Console) me permettra de l'ajuster.
