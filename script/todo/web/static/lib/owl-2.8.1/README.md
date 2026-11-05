# OWL 2.8.1, vendored unmodified

Provenance of the two other files of this directory, copied byte for byte
from the npm package. The TODO web page loads `owl.es.js` as the ES module
`@odoo/owl` through an import map; nothing here is built or edited.

- Package: `@odoo/owl` 2.8.1
- Tarball: https://registry.npmjs.org/@odoo/owl/-/owl-2.8.1.tgz
- Tarball sha1 (npm `dist.shasum`): 5a9bbe7b77590a80493fad71f7b4089a3c974329
- Tarball sha256: 80810604370473605defb016793a05e7f7768471188ba09d09135434f8b2212a
- Source: https://github.com/odoo/owl, build 5211116 of 2025-09-23
- `owl.es.js` is `package/dist/owl.es.js`
- owl.es.js sha256: 7a8d5f00f6dd74e03afba74190a6f519e56adbd2ab188ca9bdb447447ecc3a7f
- `LICENSE` is `package/LICENSE`: the LGPL-3.0 text, then the GPL-3.0 text it
  extends (package license field: `LGPL-3.0-only`)
- LICENSE sha256: ffa0c045e05e85a41a5481d59edaf40f33128374369c6d9b930bdf17bb919b89

`test/test_todo_web_static.py` checks both sha256 above against the files.
To upgrade, replace both files from the new tarball, then this README.
