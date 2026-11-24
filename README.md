# Au gré des envies – site vitrine

Site statique (HTML/CSS/JS) : couture créative, lingettes lavables, décoration florale.

## Déploiement sur Hostinger VPS (Nginx/Apache)
1. Copier le contenu de `public_html/` dans le dossier web du VPS (ex. `/var/www/html/` ou `/var/www/monsite/`) :
   `scp -r public_html/* utilisateur@IP_DU_VPS:/var/www/html/`
2. Pointer le domaine (enregistrement A) vers l'IP du VPS, puis activer HTTPS : `certbot --nginx -d votredomaine.fr`.

## À personnaliser
- Email du formulaire : `action="mailto:..."` dans `index.html` (ou brancher un vrai service d'envoi).
- Liens Instagram/Facebook dans la section Contact.
- Photos : remplacer les blocs `<div class="ph">` de la galerie par `<img src="images/...">`.
