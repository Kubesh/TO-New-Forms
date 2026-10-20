# Intuit app policy pages

`privacy.html` and `eula.html` are the two public pages Intuit asks for when requesting production
keys. They are plain, self-contained HTML (no WordPress needed) and carry a `noindex, nofollow` tag so
search engines are asked to skip them.

Parties are RZNCE LLC (developer) and Treehouse Packables LLC (customer). Before publishing, replace the
remaining placeholders:

- `adrian@rznce.com` - where questions and deletion requests go
- `[STATE / COUNTRY]` - governing law (eula.html only)

Plain-language drafts, not legal advice; have the client read them (and ideally a lawyer) once.

Publish by uploading both files to the same folder on the web host, e.g. `public_html/legal/treehouse-ops/`,
so they are served at `https://<domain>/legal/treehouse-ops/privacy.html` and `.../eula.html`. Keep them live
for as long as the Intuit app exists.

## Pages and the Intuit form

Upload all six files to the same folder (e.g. `public_html/legal/treehouse-ops/`). With `https://rznce.com/legal/treehouse-ops/`
as the folder:

| Intuit field | Value |
| --- | --- |
| End-user license agreement URL | `.../eula.html` |
| Privacy policy URL | `.../privacy.html` |
| Host domain | `rznce.com` |
| Launch URL | `.../index.html` |
| Disconnect URL | `.../disconnect.html` |
| Connect / reconnect URL | `.../connect.html` |
| Redirect URI (app keys) | `.../callback.html` |

Set `QBO_REDIRECT_URI` in `.env` to the callback URL. After approving in QuickBooks the browser lands on
`callback.html` (a real page, so no error); copy its full address into `scripts/qbo_connect.py` as usual.
The pages carry `noindex, nofollow` and `no-referrer` tags.
