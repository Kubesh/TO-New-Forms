# Intuit app policy pages

`privacy.html` and `eula.html` are the two public pages Intuit asks for when requesting production
keys. They are plain, self-contained HTML (no WordPress needed) and carry a `noindex, nofollow` tag so
search engines are asked to skip them.

Before publishing, replace the three placeholders in both files:

- `[DEVELOPER NAME]` - your name or business name
- `[CONTACT EMAIL]` - where questions and deletion requests go
- `[STATE / COUNTRY]` - governing law (eula.html only)

Plain-language drafts, not legal advice; have the client read them (and ideally a lawyer) once.

Publish by uploading both files to the same folder on the web host, e.g. `public_html/legal/treehouse-ops/`,
so they are served at `https://<domain>/legal/treehouse-ops/privacy.html` and `.../eula.html`. Keep them live
for as long as the Intuit app exists.
