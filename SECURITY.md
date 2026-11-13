# Security

JSON Imager is a desktop tool that runs locally: it has no server, no accounts, no telemetry, no
update checks and no crash reporting. This document explains how to report a vulnerability and
which boundaries the tool enforces.

## Reporting a vulnerability

**Do not open a public issue for security vulnerabilities.** Report them privately from the
repository's **Security** tab using **Report a vulnerability** (GitHub private vulnerability
reporting). Helpful details:

- the affected application version and Windows version
- the smallest JSON document, or the steps, that trigger the issue
- the expected and the observed behavior

Fixes are made to the **latest release** only.

## Threat model

**Assets:** the contents of the documents the user opens, other files on their disk, stored API
keys, their IP address and the devices on their local network.

**Primary attacker:** someone who gets the user to open an **untrusted JSON document**. Whatever
the document contains, it must not — without the user's explicit consent — make the tool read
other files from disk, write to disk, send network requests, or run code in the interface.

## Boundaries

Each boundary is tied to a check in `tools/check.py`; the checks run on every verification run.

| Boundary | How it is enforced | Check |
|---|---|---|
| Network access | Only two paths, both opened by the user: the selected Agent provider (one of the listed services, or a custom address the user enters) and image addresses enabled in Settings. No network code exists outside these two modules | `check_security` |
| TLS verification | Both network paths verify certificates through Windows' own certificate chain verifier (`truststore`), the same one the system browser uses: missing roots are fetched by Windows when needed and company root certificates are honoured. Host name checking and certificate verification cannot be turned off; there is no bundled certificate list | `check_tls_probe` |
| Interface page | Content Security Policy: the page cannot send requests on its own, inline scripts do not run, no external resources load | `check_security` |
| Document text on screen | Text is never inserted as markup (no `innerHTML`); text, tooltips and addresses in drawings are escaped | `check_security` |
| Exported HTML | Text is escaped; the file contains no tags that load external resources | `check_text` |
| Data sent to the Agent | By default only the schema: field names and types. Cell values, value-bearing labels, images and file paths are not sent. The **Data sharing** setting (off by default) adds the values of the table on screen: only that table, only its visible rows and columns, at most 100 rows and 20,000 characters, images replaced by a placeholder. While it is on, the Agent panel says so. Any other or malformed setting value sends no values | `check_schema` · `check_agent_values` |
| API keys | Stored encrypted with Windows DPAPI, never kept as plain text on disk, never sent back to the interface; carried in a request header, not in the URL. Provider requests do not follow redirects, so a key is never carried to another address | `check_keys` · `check_key_bridge` · `check_providers` · `check_custom_provider` |
| Custom provider address | The one place where a request goes to an address typed by the user. https to any host; plain http only to this computer (`localhost` or a loopback IP). No user name, password, query or fragment in the address. The rule is applied when the address is saved and again on every use, so a hand-edited settings file does not bypass it. Redirects are not followed | `check_custom_provider` |
| Images on disk | A relative path cannot leave the document's folder. An absolute path is read only with per-document permission, and the file system is not touched before permission is given. Network share (UNC) paths are never read | `_check_absolute_policy` |
| Image addresses | Off by default. When on: https only; no addresses carrying a user name or password; loopback, private, link-local and multicast IPs — written in the address or resolved — are rejected; redirects follow the same rule; size, type and time limits apply. Building a table never sends a request: a cell that holds an address is only marked, and its preview is requested after the table is drawn, through the same path as the gallery and under the same rules. With the setting off, tables show addresses as plain text | `_check_url_policy` |
| Very large images | The body of an image above 40 megapixels is not decoded | `check_gallery` |
| Editing documents | Editing changes nothing on disk. A document is written only when the user saves it, only to the file it was opened from — the interface cannot name a path. Only the values and names that changed are replaced; the result is read back and compared with the edited document before anything is written, and the write is atomic. A file that another program changed since it was opened is not overwritten without asking | `check_doc_write` · `check_json_write` · `check_json_save` |
| Saving images | When several images are saved, existing files are never overwritten; a number is appended to a conflicting name | `_check_image_export` |
| Local process | The Claude CLI provider is started without a shell, with arguments passed individually | `check_security` |
| Diagnostics text | Copied diagnostics contain no file paths | `check_about` |

## Known limitations

- **Proxy servers:** if a proxy is configured on the system, the IP of an image address is
  resolved by the proxy; the loopback and private-network check is then left to the proxy.
- **Field names reach the provider:** the schema contains field names. If field names carry
  sensitive information, do not use the Agent; each provider's data use is described in the
  Settings window.
- **With data sharing on, values reach the provider.** The visible rows of the open table go to
  the selected provider with each question. Hide columns or filter rows before asking if part
  of the table should stay local. Text inside a value can try to steer the model's answer; the
  model is told to treat values as data, but this cannot be guaranteed. The answer is shown as
  text only.
- **While image addresses are on,** the owner of an address sees that a request arrived and your
  IP address. That is what the setting does, and the Settings window says so. Requests are sent
  when the gallery is opened and when a table that holds image addresses is viewed.
- **When saving a single image,** the file is written to the path chosen in the save dialog.
- **Saving an edited document changes that file.** The first save of a session keeps the previous
  contents next to it as `<name>.json.bak`; later saves in the same session do not update that
  copy. If you choose to overwrite a file that another program changed, that program's version
  is kept as well: in the backup if none was written yet in this session, otherwise next to it
  as `<name>.json.conflict.bak`. Both copies can be turned off in Settings; with backups off,
  overwriting discards the other version.
- **"Last session" stores file paths.** It is off by default. While it is on, the paths of the
  open documents and folders are written to `session.json` next to the settings file, so they
  can be reopened on the next start; no document content is stored. Turning it off deletes the
  file. Network paths are never reopened automatically.
- **A custom provider is whoever runs that address.** The schema and, if you saved one, the key
  go to the address you entered; the tool cannot know how that service uses what it receives.
  An https address may point anywhere, including a machine on your own network.
- **The Agent can be turned off in Settings.** While it is off, the application refuses to send
  a question to any provider, not only hides the panel.
- **Documents that repeat a name inside one object** cannot be saved: the tool refuses rather
  than guess which of the repeated values an edit belongs to.
- **Malware running under the same Windows account** is out of scope: DPAPI binds keys to that
  account and does not protect them from another program running inside it.
- **Image output of very large tables** can use a lot of memory.
