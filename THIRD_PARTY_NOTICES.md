# Third-Party Notices

This repository includes third-party code imported from other open source
projects. The notices below document the original source and license terms.

The repository-level `LICENSE` file applies to this repository's own wrapper,
configuration, and maintenance code. Third-party components keep their original
licenses as documented here and in their own license files.

## CtrlApp UI

- Included path in this repository: `ctrlapp/www/`
- Component: prebuilt CtrlApp web UI
- Copyright notice found in `ctrlapp/www/index.html`: `Copyright (C) 2023, Input Labs Oy.`
- License identifier found in `ctrlapp/www/index.html`: `GPL-2.0-only`
- Bundled dependency notices: `ctrlapp/www/3rdpartylicenses.txt`

The add-on wrapper files around the web UI (`ctrlapp/Dockerfile`,
`ctrlapp/run.sh`, and `ctrlapp/config.json`) are maintained in this repository.
The prebuilt web UI under `ctrlapp/www/` is third-party software and is not
relicensed by this repository's MIT license.

## Unbound Home Assistant Add-on

- Imported path in this repository: `unbound/`
- Original source: https://github.com/fenio/ha-addons/tree/main/unbound
- Original repository: https://github.com/fenio/ha-addons
- Imported from commit: `633f0f7ef8b57cdeec7482bda93673ef043d13f2`
- Original path: `unbound/`
- License: MIT

Original license notice from `fenio/ha-addons`:

```text
MIT License

Copyright (c) 2025 fenio

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
