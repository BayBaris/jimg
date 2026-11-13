# Architecture

JSON Imager is a Windows desktop application that opens JSON documents and turns them into
tables, readable text and images. This note explains how the code is organised and which rules
hold it together. It is written for someone reading the source for the first time.

## Contents

- [Overview](#overview)
- [Repository layout](#repository-layout)
- [Data flow](#data-flow)
- [Design constraints](#design-constraints)
- [The bridge](#the-bridge)
- [Python modules](#python-modules)
- [User interface](#user-interface)
- [Data model](#data-model)
- [Output pipeline](#output-pipeline)
- [Images inside documents](#images-inside-documents)
- [Agent](#agent)
- [Files on disk](#files-on-disk)
- [Languages and themes](#languages-and-themes)
- [Startup cost](#startup-cost)
- [Verification](#verification)
- [Building and licensing](#building-and-licensing)

## Overview

- **Backend:** Python, standard library plus Pillow for raster output.
- **Window:** pywebview on the Microsoft Edge WebView2 runtime (through pythonnet).
- **Interface:** plain HTML, CSS and JavaScript — no framework, no build step, no network assets.
- **Distribution:** a single executable produced by PyInstaller.

The application is local. It has no server, no telemetry and no update check. It reaches the
network only on the user's action: when a question is sent to the agent, and when image
addresses are enabled in settings; see [Agent](#agent) and
[Images inside documents](#images-inside-documents).

## Repository layout

```text
run.py                     entry point
build.spec                 PyInstaller recipe
requirements.txt           pinned dependencies
src/jsonimager/            Python package (backend)
src/jsonimager/web/        interface: index.html, style.css, logo.svg, js/
examples/                  sample documents shipped with the app (generated)
assets/icon.ico            window and executable icon (generated)
licenses/                  license texts that are not available from installed packages
tools/check.py             verification script
tools/devserver.py         serves the interface in a browser for development
tools/make_examples.py     regenerates examples/
tools/make_icon.py         regenerates the logo and icon
tools/make_notices.py      regenerates THIRD-PARTY-NOTICES.md
```

## Data flow

```text
JSON document
  → discover.py      finds tabular datasets and their schema variants
  → flatten.py       builds columns and rows (groups, nested cells, transpose)
  → Api bridge       keeps the view state: column order, width, visibility
  → web/js/table.js  the user rearranges the table; state flows back through the bridge
  → export modules   text, PNG, SVG, PDF and draw.io are produced from that same state
```

**Output mirrors the screen.** Sorting and filtering live only in the interface. When the user
exports, the interface sends the source indices of the visible rows (`row_order`) and the
expanded rows; the backend uses them as they are. There is one sorting implementation, so the
file cannot drift from what the user saw.

**No code is written for a particular document.** Field names, dataset names and values are never
hard-coded; every rule works from the shape of the data.

### Editing and saving

Editing is a second, separate path over the same document:

```text
cell, table name or column name
  → edit_map.py    where it lives in the JSON: a value, a key, or a reason it cannot be edited
  → edit_core.py   changes the document in memory; type rules, undo and redo
  → json_write.py  on save, replaces only the changed tokens in the original bytes
```

**A cell does not carry its address.** The address is computed from the cell's position, and
the table builder and `edit_map.py` read row and column order from the same helpers, so the two
cannot disagree about which value a cell shows.

**Edits never change the document's shape.** Only a scalar value is written or a key renamed;
nothing is added, removed or reordered. Saving relies on this: the original text and the edited
document are walked side by side, and wherever a value or name differs, that token alone is
replaced. Whitespace, line endings, escapes and the spelling of untouched numbers stay as they
were. The result is read back and compared with the edited document before anything is written.

**A name is an identity.** Renaming a table changes the id of that table and of every table
below it; renaming a column changes the key that column order, width and visibility are stored
under. The bridge moves view state to the new names and moves it back on undo.

## Design constraints

- **Offline.** The executable must work without a network. No CDN, no remote fonts, no icon
  fonts.
- **No UI framework.** The Content Security Policy below rules out most of them in practice:
  icon fonts need `font-src`, positioning libraries write inline `style` attributes, and SVG
  sprites break under the `file://` origin.
- **No ES modules.** pywebview loads the page from `file://`, where module scripts fail CORS
  checks. Scripts are classic `<script>` tags loaded in order and share one global scope.
- **Strict CSP.** `default-src 'none'` and `script-src 'self'`: no inline scripts, no inline
  event handlers, no `connect-src`. All event binding happens in `web/js/main.js` with
  `addEventListener`.
- **No markup from data.** Document text is always inserted as text, never as HTML.

The security boundaries, and the checks that enforce each of them, are listed in
[SECURITY.md](../SECURITY.md).

## The bridge

Python and JavaScript talk only through the `Api` class in `app.py`, exposed to the page as
`window.pywebview.api`. Each public method is a call the interface can make.

Two pywebview behaviours shape this class:

- **Internal state must start with an underscore.** pywebview walks the attributes of the
  exposed object recursively to find callable methods. A public attribute holding a window or
  COM object sends that walk into .NET objects until it exceeds the recursion limit. Only methods
  are public; data lives in `_name` attributes.
- **No sub-objects.** For the same reason `Api` cannot hold helper objects such as
  `self.table = TableApi()`. Instead, `Api` is composed from mixin classes. A mixin is a base
  class, not an attribute, so its methods sit flat on the instance.

State is created in `Api.__init__` and shared by all mixins. The application is
multi-document: open documents are kept in `Api._docs` and most calls start with a `doc_id`.
Everything that produces output locates its table through one helper, `_table_for_output`, so
every format sees the same table under the same key.

## Python modules

**Bridge and application**

| Module | Responsibility |
|---|---|
| `app.py` | `Api` composition, shared state, window creation |
| `api_docs.py` | Opening and closing documents, folder scanning, tree, document summary |
| `api_table.py` | Table construction, transpose, view state, table lookup for output |
| `api_edit.py` | Cell editing, undo/redo, unsaved-change state and saving; moves view state when a rename changes a dataset's id |
| `api_chart.py` | Column roles, chart data and chart SVG |
| `api_export.py` | Text, PNG, vector and gallery output; writing files |
| `api_agent.py` | Agent calls, conversation history, models, API key bridge |
| `api_settings.py` | Preferences, application information, third-party attributions |

**Data**

| Module | Responsibility |
|---|---|
| `discover.py` | Finds datasets and schema variants in a JSON tree |
| `flatten.py` | Turns a dataset into columns and rows |
| `edit_map.py` | Maps a table cell back to its place in the JSON (a value or a key), or says why it cannot be edited; reads row and column order from the same helpers as `flatten.py` |
| `edit_core.py` | Writes a scalar value or renames an object key in place, with type rules and an undo/redo history; never changes the document's structure |
| `json_write.py` | Saves an edited document by replacing only the changed tokens in the original bytes (whitespace, line endings and escapes stay as they were), reads the result back before writing, and writes atomically with an optional `.bak` |
| `columns.py` | Column groups by content, shown as a second header row |
| `chart_data.py` | Chart roles and series; never imports Pillow |
| `schema.py` | Builds the schema summary and the prompt sent to an agent |
| `images.py` | Finds and reads images embedded in or referenced by a document |
| `remote_images.py` | Downloads image addresses when the user enables it |

**Output**

| Module | Responsibility |
|---|---|
| `vector.py` | Scene model; SVG, PDF and draw.io back ends |
| `draw.py` | Shared drawing helpers: fonts, measurements, PNG rendering |
| `img_table.py` | Table scene |
| `img_tree.py` | Schema tree scene and layout |
| `img_chart.py` | Chart scene |
| `export_text.py` | Report, outline, Markdown, CSV and HTML output |

**Platform**

| Module | Responsibility |
|---|---|
| `paths.py` | Asset, configuration and example locations, frozen or not |
| `settings.py` | Preferences file |
| `keys.py` | API keys encrypted with Windows DPAPI |
| `providers.py` | Agent providers: the local CLI and HTTP providers |
| `i18n.py` | Interface strings in Turkish and English |
| `theme.py` | Dark and light palettes and font stacks, shared with the CSS |

## User interface

`web/index.html` loads eleven script files in order. There are no classes: the files share a
set of global variables and plain functions.

| File | Responsibility |
|---|---|
| `state.js` | Shared state and measurements; loaded first |
| `utils.js` | DOM helpers, status line, menus, icons, clipboard, Markdown renderer |
| `tree.js` | Document and dataset tree in the sidebar |
| `table.js` | Table rendering, sorting and filtering |
| `edit.js` | Edit mode and the in-place cell editor |
| `columns.js` | Column width and order |
| `viewer.js` | SVG viewer with zoom |
| `panel.js` | Export panel |
| `chart.js` | Chart questions and picker |
| `agent.js` | Agent conversation strip |
| `shell.js` | Application menu, sidebar, settings, about dialog |
| `main.js` | Start-up and all event binding; loaded last |

Rules that follow from the single global scope:

- **Top-level names must be unique across all files.** A second declaration of the same name
  makes the later file fail with a `SyntaxError` and it does not run at all. The error appears
  only in the browser console.
- **A new file must be added to `index.html`.** The browser loads only what has a `<script>`
  tag.
- **A single element is selected by `id`.** Several dialogs share CSS classes, and a class
  selector returns the first match in the document.

## Data model

A JSON document can hold many tables. `discover.py` classifies every candidate node:

| Kind | Shape | Rows |
|---|---|---|
| `records` | array of objects | one row per object |
| `keyed` | object of objects | one row per outer key |
| `pivot` | object of objects | one column per outer key |
| `keyvalue` | object of mostly scalars | one row per key |
| `keylist` | object of arrays | one row per key, with item count |

`keyed` and `pivot` show the same data in opposite directions; the direction is chosen from the
shape (at least as many outer keys as inner keys means `keyed`). Objects keyed by identifier are the most
common table shape in JSON, so this choice matters.

Sparse data is handled by two separate mechanisms:

- **Row sparsity** — a group of fields missing from some rows — splits the dataset into
  **schema variants** (`discover.detect_variants`). Variant tables have no empty cells.
- **Column sparsity** — a column empty in most rows — only **hides** the column by default.

**View state lives in Python.** Column order, width, visibility and transpose are stored per
document, dataset and variant. Raster output has to match the screen, so this is the single
source for it.

## Output pipeline

Every image is first built as a **scene** (`vector.Scene`): positioned rectangles, lines, text
and images. The same scene is rendered by three back ends — PNG with Pillow, SVG and PDF — so
the three formats cannot disagree. The schema tree also has a node-and-edge layout that is
written as a `.drawio` file, which keeps it editable.

Text output (`export_text.py`) has report, outline, Markdown, CSV and HTML forms. HTML uses real
table cells rather than an embedded image, so its text stays selectable. Nested values, which
have no structure in Markdown and CSV, are flattened to `field=value | field=value`.

Charts start from questions the table can answer, derived from column roles
(`chart_data.py`); choosing columns by hand comes second.

## Images inside documents

The gallery shows images a document contains or points to. Where an image may come from is a
security boundary:

- **Embedded** base64 and `data:` values are always read.
- **Relative paths** are read only inside the document's own folder.
- **Absolute paths** are read only after the user allows them for that document; before that
  permission the file system is not touched.
- **UNC paths** are never read: Windows would contact the server and offer credentials.
- **Web addresses** are downloaded only when enabled in settings and only over HTTPS: for the
  gallery, for saving, and for the preview of a table cell that holds an address. Building a
  table never sends a request; the cell preview is requested after the table is drawn, through
  the gallery's path and rules. Addresses that resolve to private, loopback
  or link-local networks are refused at connection time (a configured proxy is the exception;
  see [SECURITY.md](../SECURITY.md)).

Saved images keep their original bytes and never overwrite an existing file.

## Agent

The agent answers questions about a document's structure. It is optional and does nothing until
the user sends a question.

- **Providers** (`providers.py`): a locally installed Claude Code CLI, and four HTTP providers
  that speak the OpenAI-compatible `/chat/completions` protocol (Gemini, Groq, Anthropic,
  OpenAI). A new HTTP provider is a base URL and a model list, not a new class.
- **Custom provider.** A fifth HTTP provider takes its address from the settings instead of the
  source: any OpenAI-compatible service, such as a local server. `providers.custom_endpoint` is
  the single rule for that address — https anywhere, plain http only to this computer — and it
  is applied when the address is saved and again on every use. It ships with no model list; the
  user adds model ids, and a key is optional. No HTTP provider follows redirects: `urllib` would
  carry the `Authorization` header to the new address.
- **TLS.** Both network paths share one context, `providers.tls_context()`, built with
  `truststore`: certificates are verified by Windows' own chain verifier. Python's default
  context reads only a snapshot of the Windows root store and does not trigger Windows' on-demand
  root download; on a freshly installed machine it saw 11 roots and every HTTPS request failed.
- **Only the schema is sent.** `schema.build_prompt` is the single place that builds the
  request body, for every provider. It contains dataset kinds, row and column counts, field
  names, types and fill ratios — never cell values. Columns whose names the application
  generates (such as Key and Value) are listed as such, so a model does not mistake them for
  the document's field names.
- **Data sharing is the one exception.** The `agent.send_values` setting is off by default and
  only an explicit `true` turns it on. When on, the interface names the table on screen and its
  visible row order; `api_agent._values_block` looks the table up in that document, applies the
  view (hidden columns stay out), replaces image cells with a placeholder and caps the block at
  `VALUE_ROWS` rows and `VALUE_CHARS` characters. The limits live in Python, not in the interface.
- **History is rebuilt each time.** Providers are stateless; recent turns are written back into
  the prompt within fixed limits (`HISTORY_TURNS`, `HISTORY_ANSWER_CHARS`). Only completed turns
  are kept.
- **Keys** are sent in the `Authorization` header, never in the URL, never on a command line,
  and never back to the interface. The interface can only ask whether a key is stored.

## Files on disk

The application keeps its own state in three files, all under `paths.config_dir()` rather than
next to the executable (a program installed under Program Files cannot write there):

| File | Written by | Content |
|---|---|---|
| `settings.json` | `settings.py` | Preferences, plain JSON |
| `session.json` | `settings.py` | Paths of open documents and folders; exists only while "Last session" is on |
| `keys.json` | `keys.py` | API keys, each encrypted with Windows DPAPI |

The session file holds paths only, and it is separate from the preferences because preferences
travel to the interface and paths carry a user name. Turning the setting off deletes the file.

The two are deliberately separate: people open and share a preferences file, but a key must not
travel with it. If DPAPI is unavailable the key is not written at all; there is no plain-text
fallback. Both files are written atomically, and a corrupt file is set aside instead of
crashing the application.

In the frozen executable, bundled assets come from PyInstaller's temporary folder
(`paths.asset_dir()`), while the application's own folder is `paths.project_root()`. Example
documents are copied to a permanent location on first run (`paths.examples_dir()`), because the
temporary folder changes on every start.

## Languages and themes

- **Languages.** `i18n.py` holds every interface string in Turkish and English. Python stores
  translation **keys** rather than finished sentences wherever text is kept for later, so a
  language switch never shows a stale string.
- **Themes.** `theme.py` holds the dark and light palettes. The same values exist as CSS custom
  properties, and renderers draw only with palette colours, so exported images follow the theme.

## Startup cost

Importing Pillow adds noticeably to start-up time, and the first screen does not need it. Two
rules keep it out of the start-up path:

- `images.py` imports Pillow inside the functions that decode images.
- Drawing modules (`draw.py`, `img_table.py`, `img_tree.py`, `img_chart.py`) are imported inside
  the bridge methods that draw, not at the top of the `api_*` modules.

## Verification

`tools/check.py` is the project's single verification script:

```powershell
.\.venv\Scripts\python.exe tools\check.py -q
```

With `-q` it prints one line per area and the full context only for what fails. It covers:

- **Documents:** dataset discovery and table construction on the `examples/` documents.
- **Interface source:** dead code, duplicate global names, ambiguous selectors, modal keyboard
  handling, measurements shared between JavaScript, CSS and Python.
- **Behaviour:** settings and key storage, provider requests built without touching the
  network, image source rules, a bridge smoke test.
- **Security boundaries:** see [SECURITY.md](../SECURITY.md).
- **Distribution:** executable contents, licenses and third-party notices.

`tools/devserver.py` serves `web/` over HTTP at `http://localhost:8765` and replaces
`window.pywebview.api` with a fetch-based proxy, so the interface can be developed in a browser.
File dialogs work only in the desktop window.

## Building and licensing

`build.spec` is the only build recipe:

```powershell
.\.venv\Scripts\python.exe -m PyInstaller build.spec --noconfirm --clean
```

- pywebview and pythonnet ship their own PyInstaller hooks inside their packages. The recipe
  filters those hooks out when collecting the packages; otherwise they would pull PyInstaller
  and other build tools into the executable. Build tools are also excluded explicitly, and
  `check.py` compares the contents of the last build with the runtime dependencies.
- JSON Imager is MIT licensed ([LICENSE](../LICENSE)).
  [THIRD-PARTY-NOTICES.md](../THIRD-PARTY-NOTICES.md) is generated by `tools/make_notices.py`
  from the installed packages and `licenses/`; it is never edited by hand, and `check.py` fails
  when it is out of date.
