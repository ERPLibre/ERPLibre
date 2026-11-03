# ERPLibre overrides: odoo-web-guidelines

The upstream text targets Odoo master/20 (Owl 3). ERPLibre runs Odoo 18.0 by default (Owl 2).
Where an entry below names an upstream section, the entry wins; everything not named applies
as written. First find the active Odoo version (`.odoo-version` at the ERPLibre root, else the
`odoo<ver>/` directory in use) and confirm any API against that version's sources
(`odoo<ver>/odoo`), not memory. Odoo 12-15 are not covered: verify every API there.

## [Organize files by feature, not by type](guidelines/javascript.md#organize-files-by-feature-not-by-type)

- In 18: Owl 2 has no `Plugin`. A feature folder holds the component, its service, template
  and styles: `book_card/` holding `book_card.{js,xml,scss}` and `book_card_service.js`, the
  service added to `registry.category("services")` and read with `useService`
  (`@web/core/utils/hooks`).

## [Avoid getters](guidelines/javascript.md#avoid-getters)

- In 18: Owl `computed` does not exist; write a plain method. For a cached value on a reactive
  object, `withComputedProperties` from `@web/core/utils/reactive` recomputes it when a source
  changes: `withComputedProperties(reactive({}), [books], { count(b) { return b.list.length; } })`.
- 16: `@web/core/utils/reactive` does not exist; plain method only.

## [Avoid patching JavaScript code](guidelines/javascript.md#avoid-patching-javascript-code)

- ERPLibre addons are "outside of Odoo": `patch` is the normal way to extend core or OCA
  JavaScript, unless an extension point (registry entry, prop, subclass) already fits.
- In 18 (and 17): `import { patch } from "@web/core/utils/patch";` then
  `patch(BookCard.prototype, { setup() { super.setup(...arguments); } })`.
- 16: same import, a unique name as second argument, parent via `this._super`:
  `patch(BookCard.prototype, "library.BookCard", { setup() { this._super(...arguments); } })`.
  Legacy widgets (`odoo.define(...)` modules, often in `static/src/js/`) extend with
  `Widget.include({...})`.

## Owl version and JavaScript modules

- 16 to 18 ship Owl 2 (2.8.x; the exact version is `const version` in
  `addons/web/static/lib/owl/owl.js`): no Owl 3 API (`computed`, `signal`, `Plugin`,
  `usePlugin`, `proxy`, `useProps`, `effect` from `@odoo/owl`); use `useState` and `reactive`.
- In 18 every file in `static/src/` and `static/tests/` is an Odoo module, unless its first
  comment is `/** @odoo-module ignore **/`. 16/17: only files whose first comment contains
  `@odoo-module` (usually `/** @odoo-module **/`) are; without it, `import` breaks.

## Tests in static/tests

- In 18: new tests use hoot: `*.test.js` importing `@odoo/hoot` and
  `@web/../tests/web_test_helpers`, bundle `web.assets_unit_tests`, run at `/web/tests`.
  QUnit stays for unported tests (`web.qunit_suite_tests`, `/web/tests/legacy`); add none.
- 16/17: QUnit only (`web.qunit_suite_tests`, `/web/tests`); hoot does not exist.

## Scope: addons only

- These rules do not apply to the ERPLibre mobile app under `mobile/`, an Owl application
  that is not an Odoo addon.
