---
name: monteur-video
description: Assistant de montage vidéo pour DaVinci Resolve. À utiliser quand l'utilisateur veut dérusher (couper les silences), sous-titrer en français, ajouter bandeaux de nom, titres, logos de marques animés, illustrations ou musique avec J-cut et L-cut, ou lancer l'agent de dérushage du dossier resolve-derush-agent.
---

# Monteur vidéo (agent de dérushage)

Cette skill guide l'usage de l'agent du dossier `resolve-derush-agent/` de ce dépôt et fixe les règles de montage à respecter.

## Quand l'utiliser

- Couper les silences d'interviews sans couper le dialogue.
- Générer des sous-titres français (.srt) recalés sur le montage.
- Ajouter bandeaux de nom, titres de sections, logos animés, illustrations, musique.
- Préparer une timeline importable dans DaVinci Resolve, en 16:9 ou 9:16, en 1080p ou 4K.

## Fait établi : Resolve gratuit 21.1 et scripting

D'après des sources secondaires (non confirmées par les pages officielles), le scripting Python est réservé à DaVinci Resolve Studio depuis la 21.1. Avec la version gratuite, **utiliser le mode export** (`--export`) qui produit un fichier FCPXML à importer (Fichier > Importer > Timeline). Ne jamais promettre que l'import fonctionne sans test sur la machine de l'utilisateur.

## Lancer l'agent

Depuis le dossier de l'agent (Windows) :

```
py -3 derush_agent.py "C:\montage video" --export [options]
```

| Besoin | Option |
| --- | --- |
| Silences retirés | (aucune) |
| Sous-titres français | `--sous-titres` |
| Bandeaux de nom et titres de sections | `--habillage` (remplir `habillage.json`) |
| Logos de marques citées | `--logos` (logos officiels dans `Logos/`) |
| Musique de fond | `--musique "calme, inspirant"` ou `--musique auto` |
| Illustrations web | `--illustrations` |
| Format et qualité | `--format 9:16 --resolution 4k`, ou réponse aux questions posées au lancement |
| Sans questions | `--sans-questions` (16:9, 1080p) |
| Seuil de silence | `--seuil -50` (plus bas = plus sensible) |

Dossier attendu : un sous-dossier par catégorie de rushs (`interview/`, `b-roll/`...). Les catégories `B-roll`, `Ambiance`, `Drone`, `Plans de coupe` sont gardées entières.

## Chutiers avant le montage

`py -3 derush_agent.py "<dossier>" --chutiers [--ambiances "calme, dynamique"] [--hors-ligne]` crée `Chutiers/` : 01_RUSHS (Dialogue,
B-roll, Son seul, par liens sans déplacer les originaux), 02_MUSIQUE par ambiance, 03_SFX par type, 04_LOGOS, 05_HABILLAGE,
06_SOUS-TITRES, plus INDEX_RUSHS.csv et CREDITS_CHUTIERS.json. À importer dans Resolve comme bins (clic droit sur le dossier,
« créer des bins »). Seuls des mots-clés vont sur internet. Rappeler de vérifier les licences (CC BY : citer l'auteur).

## Interface web

`py -3 pont_agent.py` lance un pont local (127.0.0.1:8765, code secret, actions listées, pages *.base44.app) que l'application Base44
« Agent monteur - Pilotage » appelle : un onglet par action, suivi en direct, historique. Ne jamais afficher ni envoyer le code secret.

## Tout automatique

`monter.bat` (double-clic) ou `py -3 derush_agent.py "<dossier>" --tout` : silences, hésitations (« euh »), prises répétées
(on garde la dernière), sous-titres, bandeaux (si `habillage.json` rempli), logos (si dossier `Logos`), musique J-cut / L-cut
(si dossier `Musique`). Le format et la qualité sont demandés. L'import dans Resolve gratuit reste manuel.

## Règles de montage

- **Silences** : ne jamais couper une phrase ; garder une marge avant (0,15 s) et après (0,25 s). Un clip jugé entièrement silencieux est gardé entier, jamais supprimé.
- **Musique** : une séquence par catégorie. J-cut : la musique suivante démarre 1,5 s avant l'image. L-cut : la musique qui se termine continue 2,5 s sous la voix suivante en s'estompant. Chevauchement en fondu, pistes A2 et A3. Toujours baissée sous la voix.
- **Sous-titres** : 2 lignes maximum, 38 caractères par ligne en 16:9 (26 en 9:16), 1 à 6 s par sous-titre, espace insécable avant `? ! ; :`. Les relire : Whisper se trompe sur accents, noms propres, chiffres.
- **Bandeaux de nom** : n'afficher que les noms saisis par l'utilisateur dans `habillage.json`. Ne jamais afficher un nom deviné ; les suggestions restent dans `_suggestion`.
- **Logos** : utiliser uniquement des logos fournis par l'utilisateur (page officielle ou kit presse), jamais téléchargés automatiquement. Rappeler de vérifier le droit d'usage (accord de la marque pour un contenu commercial ou sponsorisé).
- **Illustrations et musique en ligne** : le texte du dialogue est envoyé aux services de recherche. L'indiquer avant d'activer ces options sur un contenu confidentiel. Citer les crédits (`CREDITS.json`, `CREDITS_MUSIQUE.json`).
- **Epidemic Sound** : pas d'API de téléchargement. L'utilisateur télécharge avec son abonnement dans `Musique/`.
- **9:16** : un plan 16:9 est recadré au centre ; prévenir que le cadrage du visage est à vérifier.
- **Pistes** : V1 passages conservés, V2 illustrations, V3 bandeaux et titres, V4 logos, A1 son, A2 et A3 musique.

## Après le passage de l'agent

1. Vérifier les « grosses coupes » (silence de 3 s ou plus retiré).
2. Supprimer les illustrations qui ne collent pas au propos.
3. Contrôler crédits et licences avant publication.
4. Ajuster le niveau de la musique si besoin.

## Dépannage

- `0 segment(s)` : vidéo muette ou son trop faible. Mesurer avec `ffmpeg -i "fichier.mp4" -vn -af volumedetect -f null NUL` ; un `max_volume` de -91 dB signifie un fichier muet (fréquent avec OBS sans micro).
- `py` non reconnu : fermer et rouvrir l'invite de commandes.
- `TypeError: open() got an unexpected keyword argument 'metadata_errors'` pendant la transcription : la bibliothèque `av` (19.x) est trop récente pour faster-whisper. Corriger avec `py -3 -m pip install "av==16.1.0"`.
- Premier lancement de Whisper lent : téléchargement du modèle (environ 500 Mo).
- Windows « Contrôle intelligent des applications » : ne pas double-cliquer les `.py` ; lancer depuis l'invite de commandes.

## Limites à ne pas cacher

- L'import du FCPXML dans Resolve n'a pas été testé sur la machine de l'utilisateur ; les marqueurs de couleur ne passent pas par ce format.
- Le recadrage automatique qui suit le visage n'existe pas.
- Les logos partagent tous la même animation.
