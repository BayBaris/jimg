# Changelog

## 1.1.0

First public release. It includes everything listed under 1.0.0 below, plus:

- The collapsed sidebar is wider and keeps the full-size wordmark. Each open document shows its
  short name; clicking it lists the document's tables and schema variants, with the open one
  marked.
- Click a cell to select it and press Ctrl+C to copy its full value, or right-click it to copy
  the value or filter the table by it.
- Nested objects in text output read `key=value` instead of repeating the generated Key and
  Value column names.

## 1.0.0

First complete version (not published separately).

### What it does

- Opens JSON documents and finds the tables inside them: lists of records, objects keyed by id,
  key–value settings, side-by-side objects and keys holding lists.
- Splits records with different fields into schema variants; hides mostly empty and long-text
  columns with a notice.
- Sorts, filters, reorders, resizes and hides columns; expands nested values; transposes narrow
  tables.
- Searches all columns or one column (`@column:value`, `@column=value` for an exact match),
  with highlighted matches; exports keep only what the search left on screen.
- Exports text (report, outline, Markdown, CSV, HTML), images (PNG, SVG, PDF) of the table, the
  schema tree and charts, and the schema tree as a draw.io file. Output follows the screen.
- Suggests charts from the table's own columns.
- Shows embedded images and image paths in the table and in a gallery.
- Edits values, keys, column names and table names; saving rewrites only what changed.
- Optional Agent with six providers: Claude Code CLI, Gemini, Groq, Anthropic, OpenAI and any
  OpenAI-compatible address. By default only the schema is sent; **Data sharing** (off by
  default) adds the visible rows of the open table.
- Turkish and English interface, dark and light theme.

### Privacy

The application has no server, no accounts, no telemetry and no update check. It reaches the
network only when you send a question to the Agent or turn on image addresses. See
[SECURITY.md](SECURITY.md) for every boundary and how it is checked.

### Requirements

64-bit Windows with the Microsoft Edge WebView2 Runtime (part of Windows 11). The executable is
not code-signed; Windows may show a SmartScreen warning. Compare the file with the SHA-256 value
published with the release:

```powershell
Get-FileHash ".\JSON Imager.exe" -Algorithm SHA256
```
