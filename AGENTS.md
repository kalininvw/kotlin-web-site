# AGENTS.md

## Cursor Cloud specific instructions

This repo builds [kotlinlang.org](https://kotlinlang.org): a hybrid site with a Python/Flask
server, a Next.js app, and a webpack dev server acting as the unified entry point.
See `README.md` ("Local development" / "Tests") for the canonical commands; notes below
capture only the non-obvious caveats for this environment.

### Toolchain (already provisioned in the VM snapshot)
- Node **16.20.2** (per `.nvmrc`) via nvm. Login shells are configured (in `~/.bashrc`) to put
  Node 16 first on `PATH`; the machine's default `node` is a newer version, so always run
  `yarn`/`next`/`webpack` from a login shell (or prepend `$HOME/.nvm/versions/node/v16.20.2/bin`).
- Python **3.8** venv at `.venv/` (the pinned Flask stack does not build on the system Python 3.12).
  Run the server with `./.venv/bin/python kotlin-website.py`.
- Ruby **kramdown 1.14.0** gem is required at runtime — non-docs Markdown pages are rendered by
  shelling out to `kramdown` (see `src/markdown/makrdown.py`).

### Running the site (three services)
Run each in its own terminal from a login shell:
- Flask server → `./.venv/bin/python kotlin-website.py` (port **8080**)
- Next.js dev → `yarn next-dev` (port **3000**)
- Webpack dev server → `yarn start` (port **9000**, the unified entry point)

The webpack dev server proxies `/_next/**` and `/community/**` to Next.js (`:3000`) and everything
else to Flask (`:8080`); it serves `/_assets/**` itself.

`out/` (the Next.js static export) must exist for Flask to serve `/`, `/community/*`, `/404.html`.
Regenerate it with `yarn next-build-static` when Next pages change (it is a build step, not part of
the startup update script).

### Known caveats / gotchas
- **Styled homepage:** at `:9000` the homepage `/` renders **unstyled**. Flask serves the static
  export `out/index.html`, whose build-hashed `/_next/*` assets exist in `out/_next` (served fine by
  Flask at `:8080`) but the dev proxy routes `/_next/**` to `next-dev`, which 404s those hashes.
  View the fully-styled homepage and other Next pages via **`next-dev` at `http://localhost:3000/`**
  during development. Flask-rendered pages (e.g. `/education/`) and the proxied `/community/` are
  fully styled at `:9000`.
- **`geocoder` dependency:** the `git+https://github.com/pik-software/geocoder.git` line in
  `requirements.txt` points at a deleted repo (404) and is skipped when installing. It is only used
  by the optional `scripts/*_geolocator.py` scripts, never by the server.
- **`/docs/*` and e2e tests:** docs pages are served from `dist/docs/` and the WebHelp/API e2e
  visual tests (`test/e2e`) need TeamCity artifacts in `dist/` and `libs/` plus reference snapshots,
  which are not available here — those tests can't run locally without downloading artifacts.
- **Webpack overlay:** a black "Compiled with problems" overlay for
  `kotlin-playground … Can't resolve 'data:text'` is a harmless warning; dismiss it.
- **Playwright browser:** install with `npx playwright install chromium` (no `--with-deps`; the
  pinned Playwright 1.22.2 `--with-deps` references package names that don't exist on Ubuntu 24.04).

### Lint / test
- Lint: `yarn lint` (Next.js ESLint over `blocks`, `components`, `pages`).
- Tests: Playwright (`yarn test*`). See README "Tests"; e2e visual tests need the artifacts noted above.
