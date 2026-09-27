# xterm.js fit addon 0.10.0, vendored unmodified

Provenance of the two other files of this directory, copied byte for byte
from the npm package, released with xterm.js 5.5.0 (peer dependency
`@xterm/xterm` ^5.0.0). The TODO web page loads `addon-fit.js` as a classic
script, which defines the global `FitAddon`, whose `FitAddon` property is the
addon class; nothing here is built or edited. `addon-fit.js` names a source
map, `addon-fit.js.map`, left out: the hub serves no `.map` file.

- Package: `@xterm/addon-fit` 0.10.0, published 2024-04-05
- Tarball: https://registry.npmjs.org/@xterm/addon-fit/-/addon-fit-0.10.0.tgz
- Tarball sha1 (npm `dist.shasum`): bebf87fadd74e3af30fdcdeef47030e2592c6f55
- Tarball sha256: 917ac44972453d5eed52edc1e50260c76398ce48cf2290c2e60671102bba0b33
- Source: https://github.com/xtermjs/xterm.js/tree/master/addons/addon-fit
- `addon-fit.js` is `package/lib/addon-fit.js`
- addon-fit.js sha256: bdaefa370b1bfc42ee88d46fe6072400902a4d4b2d45cd93438dda9b23c97089
- `LICENSE` is `package/LICENSE`: the MIT license (package license field:
  `MIT`)
- LICENSE sha256: e256f01188af527e4d06d21d06fbf785ae9c50d4b328bf03cbe0ba7f0aa4228f

`test/test_todo_web_static.py` checks both sha256 above against the files.
To upgrade, replace both files from the new tarball, then this README.
