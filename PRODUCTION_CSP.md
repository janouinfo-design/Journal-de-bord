# Configuration CSP pour la production Logitrak

## Contexte

L'app Livre de bord est embarquée en iframe dans l'interface Navixy white-label
sur `login.logitrak.fr/#/user-app/*`. Pour que l'iframe fonctionne, le serveur
qui sert le HTML **doit** :

1. Ne PAS envoyer de `X-Frame-Options: DENY` ou `SAMEORIGIN`
2. Envoyer un `Content-Security-Policy: frame-ancestors …` qui inclut les
   domaines Navixy white-label

## État actuel (20/07/2026)

| Environnement                                        | CSP en place | Iframe OK |
|------------------------------------------------------|--------------|-----------|
| Preview (`trip-classifier-2.preview.emergentagent.com`) | ✅ oui, explicite | ✅ |
| Production (`documents-web.logitrak.ch`)             | ❌ aucun     | ✅ (par défaut, rien ne bloque) |

**La prod fonctionne déjà** parce qu'aucun header restrictif n'est envoyé.
Néanmoins, ajouter explicitement le CSP est **recommandé** pour :
- Documenter l'intention
- Éviter qu'un futur reverse-proxy ajoute un `X-Frame-Options` restrictif par
  défaut et casse l'intégration

---

## Comment ajouter le CSP en production

### Option 1 — Cloudflare Transform Rules *(recommandé, 5 min)*

1. Dashboard Cloudflare → sélectionnez le domaine `logitrak.ch`
2. **Rules → Transform Rules → Modify Response Header** → **Create rule**
3. Nom : `Livre de bord — iframe CSP`
4. Condition :
   - Field: `Hostname`
   - Operator: `equals`
   - Value: `documents-web.logitrak.ch`
5. Set static → header name `Content-Security-Policy`, header value :
   ```
   frame-ancestors 'self' https://*.logitrak.fr https://logitrak.fr https://*.logitrak.ch https://logitrak.ch https://*.navixy.com https://*.navixy.io;
   ```
6. Déployer

### Option 2 — Fichier `_headers` dans le build *(si Cloudflare Pages ou Netlify)*

Déjà présent dans `/app/frontend/public/_headers` — il sera copié dans le build
et lu automatiquement à chaque déploiement.

### Option 3 — nginx.conf *(si VPS custom avec nginx en front)*

Ajouter dans le server block du domaine :

```nginx
server {
    server_name documents-web.logitrak.ch;
    # ...
    add_header Content-Security-Policy "frame-ancestors 'self' https://*.logitrak.fr https://logitrak.fr https://*.logitrak.ch https://logitrak.ch https://*.navixy.com https://*.navixy.io;" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header X-Content-Type-Options "nosniff" always;
}
```

Puis `nginx -t && systemctl reload nginx`.

---

## Vérification après déploiement

```bash
curl -sI https://documents-web.logitrak.ch/ | grep -i content-security
```

Doit retourner la ligne `content-security-policy: frame-ancestors …`.

## Preview (dev)

Configuré via `craco.config.js` → `devServer.headers`. Déjà actif :

```bash
curl -sI https://trip-classifier-2.preview.emergentagent.com/ | grep -i content-security
```
