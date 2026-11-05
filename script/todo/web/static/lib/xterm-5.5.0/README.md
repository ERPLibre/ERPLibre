# xterm.js 5.5.0, vendored unmodified

Provenance of the three other files of this directory, copied byte for byte
from the npm package. The 5.x packages ship no ES module build: the TODO web
page loads `xterm.js` as a classic script, which defines the global
`Terminal`, and `xterm.css` as a stylesheet; nothing here is built or edited.
`xterm.js` names a source map, `xterm.js.map`, left out: the hub serves no
`.map` file.

- Package: `@xterm/xterm` 5.5.0, published 2024-04-05
- Tarball: https://registry.npmjs.org/@xterm/xterm/-/xterm-5.5.0.tgz
- Tarball sha1 (npm `dist.shasum`): 275fb8f6e14afa6e8a0c05d4ebc94523ff775396
- Tarball sha256: bd954fa721872170188cc5d7e83e88db3c83c9a18a4e8d24c2783d26491f59d2
- Source: https://github.com/xtermjs/xterm.js
- `xterm.js` is `package/lib/xterm.js`
- xterm.js sha256: 1f991ac3b4b283ebf96e60ae23a00a52765dd3a2e46fa6fdda9f1aab032f7495
- `xterm.css` is `package/css/xterm.css`
- xterm.css sha256: ba8e6985669488981ccf40c0cefe3aba80722cb6c92de7ad628b0bd717faf2b6
- `LICENSE` is `package/LICENSE`: the MIT license (package license field:
  `MIT`)
- LICENSE sha256: b569f629d00f2626a8100df2a1798210535621e42164dfd426a6fe5aac7b0ccd

`test/test_todo_web_static.py` checks the three sha256 above against the
files. To upgrade, replace the three files from the new tarball, then this
README.
