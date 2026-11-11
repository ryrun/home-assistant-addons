# ryrun Home Assistant Add-ons

Home Assistant add-on repository maintained by ryrun.

## Add-ons

- `ctrlapp`: CtrlApp UI served as a Home Assistant add-on.
- [`einkdisplaymanager`](einkdisplaymanager/README.md): Local OpenPaper L media library, image optimization, and device slideshows (experimental).
- [`trakt-mcp`](trakt-mcp/README.md): Read-only Trakt MCP server with setup, logs, and an Ingress service monitor in Home Assistant (experimental).
- `unbound`: Unbound DNS resolver add-on imported from `fenio/ha-addons`.

## License

The repository's own wrapper, configuration, and maintenance code is licensed
under the MIT License. See `LICENSE`.

This repository also contains third-party software with its own license terms:

- `ctrlapp/www/`: prebuilt CtrlApp web UI, marked as `GPL-2.0-only` by
  Input Labs Oy in `ctrlapp/www/index.html`.
- `unbound/`: imported from `fenio/ha-addons`, licensed under MIT.

See `THIRD_PARTY_NOTICES.md` and each add-on's `UPSTREAM.md` file for source
and license details.
