# ERPLibre overrides: odoo-security

The upstream SKILL.md targets Odoo master (20.0). ERPLibre runs Odoo 18.0 by default.
Where an entry below names an upstream section, the entry wins. Every section it does not name applies as written.
Before applying anything, find the active Odoo version of the checkout: `.odoo-version` at the ERPLibre root, or else the `odoo<ver>/` directory in use. Then check every API against that version's sources (`odoo<ver>/odoo`), not against memory.
The `16/17:` notes appear only where those versions differ from 18. Odoo 12-15 are not covered: for them, verify every API in the sources of the active version.

## [Process](SKILL.md#process)

- In 18, the `security/` files to review are `ir.model.access.csv` and the XML that declares `res.groups` and `ir.rule` records. `ir.access.csv` does not exist (see Access control).
- Sweep table in 18:
  - `t-raw` is not dead code. It is a live unescaped sink: flag every hit (see Prevent XSS).
  - `t-esc` is not a finding by itself, because it renders escaped.
  - Judge the domain row with `expression.AND` (see Domain injection).
  - Add `ir.model.access.csv` rows whose `group_id:id` is empty, judged against Access control.
  - Add `@classmethod`/`@staticmethod` on a model, judged against Default to private methods.
  - Add the jQuery HTML sinks `.html(`, `.append(`, `.prepend(`, `.after(`, `.before(`, `.replaceWith(`, `.wrap(`, and `$(` on a string, judged against Prevent XSS.
- 16: keep `SQL(` in the sweep. There it is psycopg2's `sql.SQL`, whose string is trusted as raw SQL, so judge any non-literal or interpolated argument as injection. Also sweep `cr.execute` and the string building that feeds it.
- 16: also sweep `t-raw` in client templates rendered by the legacy QWeb2 engine: any template in `static/src/**/*.xml` whose `t-name`/`t-extend` element lacks `owl="1"`. In those, `t-raw` is pushed unescaped.

## [Access control](SKILL.md#access-control)

- The model that the upstream text and its odoo-guidelines links describe does not exist in 16-18. That model is `ir.access` with `operation`/`domain` columns, group-less rows as restrictions, and `base.group_everyone`. In 16-18 there are two mechanisms, and a group-less row means OPPOSITE things in each:
  - **`ir.model.access`** (`security/ir.model.access.csv`) grants access to a whole model. Its header is `id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink`, with values `1`/`0`, and it has no domain. Rows are OR-ed over the user's groups, and a model with no row is inaccessible. **A row with an empty `group_id:id` grants that access to EVERY user, portal and public included.**
  - **`ir.rule`** (XML: `model_id`, `groups`, `domain_force`, `perm_*`) restricts which records the ACL already granted. A rule never grants anything. A rule with no `groups` is global and is AND-ed for every user, so global rules that do not overlap lock everyone out. Group rules are OR-ed together across the user's matching groups, and that result is AND-ed with the global rules. So a group rule restricts only members of its group, and any other group rule the same user gets on that model and operation widens it. To restrict everybody, use a global rule.
- Flag `perm_create`, `perm_write` or `perm_unlink` = `1` on an ACL row whose group is empty, `base.group_portal` or `base.group_public`. Scrutinize `perm_read` = `1` on those rows too. A portal grant should come with an `ir.rule` for `base.group_portal` that limits it to the user's own records (for example through `user.partner_id`). A public grant should come with an `ir.rule` for `base.group_public` that limits it to records meant for anonymous exposure. All visitors share one public user, so an ownership rule does not isolate them. `base.group_everyone` does not exist in 16-18.
- The `perm_*` fields of an `ir.rule` default to True, so a rule covers all four operations. Unchecking one exempts that operation from THIS rule only: it is then governed by the ACL and the other rules on the model, and by the ACL alone when no other rule covers it. `write()` checks only write access and write rules, never read rules. Keep the defaults on a restricting rule unless the split is deliberate.
- Multi-company: use a global `ir.rule`. `company_ids` (the user's active allowed companies) is available in the rule evaluation context. Drop the `('company_id', '=', False)` branch when `company_id` is required:

```xml
<record id="library_book_rule_company" model="ir.rule">
    <field name="name">Book: multi-company</field>
    <field name="model_id" ref="model_library_book"/>
    <field name="domain_force">['|', ('company_id', '=', False), ('company_id', 'in', company_ids)]</field>
</record>
```

- Sensitive models need `ir.rule` records in addition to the ACL rows. `sudo()` bypasses both.

## [Default to private methods](SKILL.md#default-to-private-methods)

- `@api.private` exists in 16-18, and the guard checks it across the MRO. The guard, `get_public_method` in `odoo/service/model.py`, blocks only `_`-prefixed names, `@api.private`, and a fixed list of unsafe attribute names. **It does not block classmethods or staticmethods.** A public `@classmethod` or `@staticmethod` on a model can be called over RPC.
- The fix is a `_` prefix, or `@api.private` placed BELOW `@classmethod`/`@staticmethod`. Above them, the flag lands on the descriptor and the guard never sees it:

```python
@classmethod
@api.private
def compute_isbn(cls, code): ...
```

## [Use the ORM; parameterize SQL](SKILL.md#use-the-orm-parameterize-sql)

- 16: `odoo.tools.SQL` is psycopg2's `sql.SQL`, re-exported. It is not Odoo's wrapper: it takes no parameters and has no `SQL.identifier`. Pass values as `cr.execute(query, params)`, and take identifiers from a whitelist or `psycopg2.sql.Identifier` (`SQL("... {}").format(Identifier(name))`). `Query.select()` takes plain strings and returns `(query, params)`, as in `cr.execute(*Book._search(domain).select('"library_book"."id"'))`. `_search` returns `[]` rather than a `Query` when the domain is trivially false, so check for that first. `_read_group` keeps the old `(domain, fields, groupby, ...)` signature.

## [Domain injection](SKILL.md#domain-injection)

- There is no `Domain` class in 16-18 (`fields.Domain` exists only in master). Combine domains with `odoo.osv.expression.AND([security_domain, user_domain])`. It normalizes each operand, so an injected `'|'` stays inside its own operand. Never write `security_domain + user_domain`.

## [Routes: auth, POST, CSRF](SKILL.md#routes-auth-post-csrf)

- In 16-18 there is no `jsonrpc` or `json2` route type and no `/json/2` endpoint: JSON routes use `type='json'`. They have no CSRF token check. Their protection is that the dispatcher accepts only JSON content types (`application/json`, `application/json-rpc`), which a cross-site HTML form cannot send.

## [Prevent XSS (escape on the way into the DOM)](SKILL.md#prevent-xss-escape-on-the-way-into-the-dom)

- Server QWeb 16-18: **`t-raw` still exists (deprecated) and outputs its value UNESCAPED**, because it wraps the value in `Markup`. Flag every `t-raw` as an XSS sink, not as broken code. Fix it with `t-out`, and use `Markup` only on trusted HTML.
- `t-esc` works and escapes, both in server QWeb (deprecated) and in OWL. It is not a bug, but write `t-out` in new code.
- OWL 16-18: `t-raw` is a deprecated alias of `t-out`. It escapes unless the value is `markup()`, and it logs a console warning.
- 16: the legacy QWeb2 JS engine (`web/static/lib/qweb/qweb2.js`, used by legacy widgets) pushes `t-raw` unescaped, so it is a live sink there too. In 16, a client template is QWeb2 when its `t-name`/`t-extend` element has no `owl="1"`, and OWL otherwise.
- JS helpers in 18: `@web/core/utils/html` exports only these three:
  - `htmlEscape`, which returns a `markup()` value and leaves an already marked value unchanged;
  - `isHtmlEmpty`;
  - `setElementContent(el, content)`, which sets `innerHTML` for a `markup()` value and `textContent` otherwise.

  `setInnerHtml` and `htmlJoin` do not exist.
- 16/17: there is no `@web/core/utils/html`. Escape with `htmlEscape` from `@odoo/owl` or with `escape` from `@web/core/utils/strings`.
- jQuery ships in 16-18, and public widgets, website and legacy code use it. Its HTML sinks are `.html(str)`, `.append/.prepend/.after/.before/.replaceWith/.wrap(str)`, and `$(str)` when the string holds markup. Never feed them user or low-privilege strings. Use `.text(str)`, or escape first.
- 16: `_()` does not escape its arguments, even when one is `Markup`; it returns a plain `str`. Build the HTML as `Markup(_("<b>%s</b>")) % value`, which escapes `value`.

## [`eval` is evil](SKILL.md#eval-is-evil)

- `--unsafe-policy` does not exist in 16-18, so ignore that clause. `safe_eval` is the single module `odoo.tools.safe_eval`.

## [Never `pickle`](SKILL.md#never-pickle)

- 16/17 still ship `odoo.tools.misc.pickle`, a wrapper that restricts unpickled globals to a whitelist. Use `json` anyway, and flag the builtin `pickle` on any data that is not fully trusted.

## ERPLibre: scope

- These rules apply to Odoo addons (a directory holding `__manifest__.py`) and to the core under `odoo<ver>/odoo`. ERPLibre tooling (`script/`, `mobile/`, deployment files) is not addon code: audit it with a generic security review.

## ERPLibre: justification comments and reports

- A comment that justifies a `sudo()`, a widened ACL row or a `csrf=False` states the technical constraint or the failure mode it prevents, in the present tense. It never names the incident, date, customer, database, host or person (`.claude/rules/04-code-conventions.md`).
- Findings, fixes, tests and proofs of concept carry nothing identifying: no customer or organisation name, real database name, host, IP address, e-mail, or value taken from customer data. Name the class of situation instead ("on a production database"), and invent the attack values.
- Commit a fix under the convention of its repository class, which `script/git/commit_convention.py <path>` prints: `odoo` and `oca` follow odoo-git (with the OCA deviations for `oca`), and `erplibre` follows `/commit`. In every class, add an `Assisted-by: <model>` trailer for any AI involvement. Never put an AI in `Co-authored-by`, and add no session-link trailer.
