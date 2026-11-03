# Changelog

## 3.0.0-dev.31

- **The framework layer is gone** (asked for by the user): UCCIF is one core that fits any project,
  with no knowledge of a particular framework. Removed: Vue template parsing (`renders`, template
  calls, `passes_prop` / `listens` / `emits`), Pinia stores (`calls_action`, `reads_state`,
  `uses_store`), `uses_composable`, vue-router routes and navigation (`routes_to`,
  `navigates_to`), CSS links (`uses_css_var`, `defines_css_var`, `uses_class`), and with them the
  `--component`, `--store`, `--route`, `--css-var` queries, `index graph --mode components`, the
  `store` / `vue` / `css` / `route` kind groups and the optional `tree-sitter-html` grammar.
- **The core is unchanged:** symbols, imports (aliases, barrels), calls (with variable origins and
  class methods through base classes), callbacks, inheritance, type references, reads / writes of
  module variables, tests, git co-change, `--impact` / `--path`, the graph view, Go / Rust / Java.
  A `.vue` / `.svelte` file is still read for its `<script>` (file-type support), and CSS files keep
  their `--var` / `$var` / `@mixin` symbols.
- Every top-level JS/TS variable is a `variable` symbol now (before, a call result such as
  `const s = make()` was skipped and `ref()` / `computed()` were a separate `ref` kind).
- `SCHEMA` 16: an older index is rebuilt automatically; the `tags`, `tag_uses`, `navs`, `css_uses`
  and `globals` tables are dropped. The parser keeps its 15-item result (the framework slots are
  reserved, always empty).
- `tests/bench_index.py --synthetic N` generates a plain TypeScript + Python app (modules importing
  each other, classes, a barrel, module state). With tree-sitter: 200 modules (257 files) touch-1
  136 ms; 800 modules (1007 files) touch-1 20 ms with the derived edges deferred (catch-up 2.5 s in
  the next full-scan update). Without tree-sitter: 16 / 38 ms. Budget 300 ms.

## 3.0.0-dev.30

- **Go, Rust and Java** (roadmap layer E), each with its own optional grammar
  (`pip install tree-sitter-go tree-sitter-rust tree-sitter-java`; CI's tree-sitter job installs
  them, `uccif doctor` names what is missing). Without the grammar a file is indexed by regex as
  before. Symbols, imports, calls and inheritance at the level of JS/Python, in `ts_other.py`:
  - **Go:** functions, methods (scope = receiver type), structs / interfaces, package-level
    const / var. An import names a package, i.e. every file of its folder (module path from
    `go.mod`). Calls resolve through `pkg.Func()`, to functions of the same package in other files
    (no import needed), and to methods through receivers and typed parameters (`s *store.Store`
    -> `store.Store.Save`, found in whichever file of the package defines it). Built-ins (`len`,
    `append` ...) and other modules' packages (`fmt`) are external.
  - **Rust:** functions, `impl` methods (scope = type), structs, enums, traits, consts; `mod x;`,
    `use crate::a::b`, `use self:: / super::`, grouped and aliased `use`, files `x.rs` or
    `x/mod.rs`. Calls: `helper()`, `util::other()`, `Order::new()`, `self.base()`, methods through
    typed parameters / lets. `impl Trait for Type` is an `implements` edge. std types are external.
  - **Java:** classes, interfaces, enums, records, methods, constructors; `import a.b.C` (and
    `a.b.*`, a whole package). Calls through imported classes (`Util.go()`), same-package classes
    without an import, `this.x()`, `new Foo()`, and typed parameters / fields / locals (`Helper h;
    h.help()`). `extends` / `implements` edges. `java.lang` types are external.
- Typed languages use the declared type of receivers, parameters, fields and locals; names of the
  same Go / Java package are looked up in the file's folder after all files are known (derived,
  so a function moved to another file of the package stays linked).

## 3.0.0-dev.29

- **Smaller index** (`SCHEMA` 15, an older index is rebuilt automatically): the legacy `imports` and
  `calls` tables, written alongside `edges` since dev.13, are dropped. `--file` and `index status`
  read imports from `edges` (`imports` / `imports_ext`), the benchmark counts from `edges`.
  DB size: fixture 240 -> 212 KB, this repo 3368 -> 2648 KB, a 200-component app 4316 -> 3840 KB.
  The `symbols` table stays (small; every symbol query uses it).

## 3.0.0-dev.28

- **Big-repo benchmark and lazy derived edges.** `tests/bench_index.py --synthetic N` generates a
  Vue 3 + Pinia + router app with N components (each importing and rendering two others with props
  and emits, using a store, a composable, a util through a barrel, types, CSS variables and scoped
  classes; routed views navigating to each other) and benches it next to the other targets.
  - Measured before this change: one-file update 59 ms at 200 components, **353 ms at 800**, over the
    300 ms budget: the derived passes (barrels, components, store members, CSS, variables ...) are
    recomputed from the whole repo after every change.
  - As the plan prescribes for a layer over budget, they are now **lazy on big repos**: each full
    pass records its duration; when it exceeded 150 ms, the post-Edit one-file update keeps direct
    edges current, marks the derived ones stale and the hook starts `uccif maintain` in the
    background. The next full-scan update (every query runs one first) catches up, so answers are
    never stale. Small repos are unchanged (still computed inline). `index status` says whether
    derived edges are current or pending.
  - Now: 800 components: one-file update **6 ms**, background catch-up 347 ms, no-op 24 ms;
    200 components: 57 ms inline; the fixture: 8 ms.
- The benchmark table has a `catch-up ms` column.

## 3.0.0-dev.27

- **Scope analysis for `reads` / `writes`**: names that shadow a module variable inside a function
  (parameters, destructured parameters, local `const`/`let`, `for (const x of ...)`, `catch (x)`) and
  template locals (`v-for` aliases, slot props `#item="{ row }"`) no longer count as using it, while a
  default value (`(n = total) => ...`) still reads it. With that, `reads` / `writes` are `extracted`
  instead of `inferred` (dev.22 documented the shadowing as a known limit; it is gone).
- Nested anonymous callbacks count as their enclosing named function, so a callback parameter
  that shadows a module variable hides it in the whole function: conservative (a missed edge, never
  a wrong one).

## 3.0.0-dev.26

- **Fewer false leads** (the unresolved share on this repo was 50%, over the plan's 30% limit;
  now 25%; the vue-app fixture stays at 8%):
  - Python `from pkg import module` and `from . import module` now bind the name as a namespace,
    so `module.func()` resolves to `pkg/module.py#func` (before, only a bare `module()` call did).
    This alone resolved several hundred calls here (`index.update()`, `task.load()` ...).
  - A built-in method (`execute`, `append`, `get` ...) called on a variable that came from a repo
    function or class we could not tie it to (`con = connect(); con.execute()`, where `connect`
    returns `sqlite3.connect(...)`) is `calls_ext` unless the repo defines such a method; anything
    else stays an `unresolved` lead.
  - Methods of pytest's built-in fixtures (`monkeypatch`, `capsys`, `tmp_path`, ...) are external.
- What remains unresolved: method calls on parameters whose type the code does not write
  (`n.child_by_field_name()`), and built-in names the repo also defines (kept as leads on purpose).

## 3.0.0-dev.25

- **Graph view upgrade** (phase 2, step 13), still one self-contained HTML page:
  - Links carry every edge family between two files: imports, calls, components (renders /
    props / emits), stores, routes, css, types, variables, inheritance. A checkbox per family
    (with its count) filters them, and an `inferred` toggle hides links that rest only on name or
    pattern matches (drawn dashed). The side panel names the families of each link.
  - `uccif index graph --mode components`: the Vue render tree (components only, `renders` edges).
  - `uccif index graph --file <path>`: function level for one file: its functions, components,
    props, emits, store members… and the symbols they touch one hop away, coloured by file, each
    with `file:line` and the `--impact <name>` command to run.
  - Checked in Chromium on the fixture in all three modes: no script errors.

## 3.0.0-dev.24

- **Graph queries** (phase 2, step 12), all read-only, at most 30 lines, `file:line` on every row:
  - `--impact` takes a symbol as well as a file: who uses it through any edge (calls, store actions
    and state, renders, props, routes, CSS variables, types, variables, callbacks), then who uses
    those, level by level, with the tests to run. `--kinds` narrows to edge kinds or groups
    (`code`, `store`, `vue`, `css`, `route`, `types`, `vars`); an unknown kind is reported with the
    list. By default only `extracted` edges are followed and the head line says how many more files
    `inferred` edges would add; when nothing is certain, the inferred picture is shown instead.
    `--min-confidence inferred` follows both. The same default now applies to `--impact <file>`.
  - `--component <Name>` (kebab-case accepted): rendered by, renders, props with who passes them,
    emits with who emits and listens, routes that show it, stores and composables it uses.
  - `--store <name>` (`trip` finds `useTripStore`): actions, state and getters with their users.
  - `--route <path or name>`: the component shown and every navigation to it.
  - `--css-var=--x` (or `--css-var x`): definitions and uses. `--cochange <file>`: git pairs.
- Session hint lists the new queries (one line); `smart-code-search`, `code-impact-analysis`,
  `code-impact-analyzer`, `project-analyst` and `change-reviewer` use them. README has a query table.

## 3.0.0-dev.23

- **Files that change together** (phase 2, step 11, roadmap D5; `SCHEMA` 14, an older index is
  rebuilt automatically).
  - `co_changes` edges (`inferred`, both directions) from the last 300 non-merge commits
    (`git log --name-only`): a pair of indexed files changed together in at least 2 commits and in
    at least 30% of the commits touching the rarer of the two. Commits touching more than 30 files
    (formatting, renames, vendoring) are ignored. `detail` holds the evidence ("3 commits (100%)").
  - Cached by HEAD: git runs only when HEAD moved, never in the one-file update after an Edit.
    11 ms on this repo's 47 commits. Deleted files drop their pairs.
  - `--file` shows `Often changed with (git): view.ts [3 commits (100%)]`. Not part of `--impact`'s
    default edges (history is a hint, not a dependency); a `--cochange` query comes with the query
    step.

## 3.0.0-dev.22

- **Types and variables** (phase 2, step 10; `SCHEMA` 13, an older index is rebuilt automatically).
  - `references_type` (D1, `extracted`): a type used in a signature, annotation, generic argument or
    props type (TS `type_identifier`s; Python parameter / return / variable annotations), to the
    interface / type / class / enum that defines it, also through barrels. Generic parameters (`T`)
    and built-in types (`list`, `string`) add nothing. `--impact types/trip.ts` lists every file
    whose signatures use its types.
  - `reads` / `writes` (D2, `inferred`): module-level variables and top-level `ref()` / `reactive()` /
    `computed()` of a script (new `variable` / `ref` symbols, exported or not), used from functions
    of the same file, from other files that import them, and from the template (`{{ tab }}`,
    `v-model="title"` is a write, `tab.value = x` is a write of `tab`). One edge per user and
    variable. `inferred` because names are matched without scope analysis: a local or parameter
    that shadows the variable is not told apart (documented, tested). Local variables inside
    functions are not tracked.
  - Both are derived from the whole repo after each update, so renaming the variable or type
    removes stale edges. `--symbol` shows them in `Used by (n)`.
- Measured: one-file update 8 ms on the fixture (budget 300 ms), so no lazy mode was needed; DB +2%.
  Unresolved share: fixture 8%, this repo 51%.
- Not yet: Python module variables (only annotations for Python), JSDoc types.

## 3.0.0-dev.21

- **CSS variables and classes** (phase 2, step 9; `SCHEMA` 12, an older index is rebuilt
  automatically). Regex based, so it also works without tree-sitter (template classes need the
  HTML grammar).
  - New definitions: CSS custom properties inside `<style>` blocks of `.vue`/`.svelte` files (CSS
    files already had them) and class selectors (`.btn`, `.card:hover > .title`, nested SCSS) in
    stylesheets and `<style>` blocks, as `css_class` nodes (`detail` = `scoped` for
    `<style scoped>` / `<style module>`). Comments, `@media` preludes, attribute values and numbers
    (`0.5s`) are not mistaken for classes.
  - `uses_css_var` (D3): every `var(--x)` (CSS, `<style>`, inline `style=`, CSS-in-JS strings) and
    `getPropertyValue('--x')`, to each definition of the variable (`extracted`); a variable defined
    nowhere in the repo (a library's) is an `unresolved` lead. `defines_css_var`:
    `el.style.setProperty('--x', ...)`.
  - `uses_class` (D4, `inferred`): a template class (`class="a b"`, `:class="{ a: x }"`,
    `:class="['a']"`) to a selector of that exact name: the component's own `<style>` first, else
    stylesheets and unscoped `<style>` blocks; another component's scoped style never counts, and
    classes with no selector (utility CSS) add nothing.
  - `--impact tokens.css` lists the components using its variables ("uses CSS variable --brand-color
    at :11"); `--symbol --brand-color` shows `Used by (n)`. Recomputed after every update, so a
    renamed variable turns its users into leads.
- Measured: one-file update 8 ms on the fixture (budget 300 ms); DB +10%. Unresolved share: fixture
  9%, this repo 51%.

## 3.0.0-dev.20

- **Deeper call resolution** (phase 2, step 8; `SCHEMA` 11, an older index is rebuilt automatically).
  - **Callbacks (C2):** a function handed to another call is a `passes_callback` edge from the caller
    to it: `watch(src, sync)`, `onMounted(init)`, `xs.map(this.fmt)`, Python `Thread(target=worker)`,
    `sorted(xs, key=fn)`. Identifiers that turn out not to be functions (data, constants) add nothing.
    Shown in `--symbol` `Used by` and followed by `--impact`.
  - **Late resolution (C3):** an import of a path that did not exist yet (and the calls through it)
    used to stay unresolved until the importer was edited. When new files appear, the importers
    whose unresolved import now resolves are re-parsed once in the same update; other importers
    are left alone.
  - **Built-in methods (rest of C1):** a call like `items.map()`, `s.toFixed()`, `cur.execute()` on a
    receiver we cannot place is `calls_ext` (known, not repo code) unless some file of the repo
    defines a function or method of that name, in which case it stays an `unresolved` lead. Decided
    from the whole repo after each update, so adding such a method flips it back.
- Measured: one-file update 7 ms on the fixture (budget 300 ms). Unresolved share: fixture 10% (was
  16%), this repo 50% (was 66%): what remains are method calls on parameters and locals whose type
  is not written in the code (`project.root`, `con.execute` where `con` is a parameter).

## 3.0.0-dev.19

- **vue-router** (phase 2, step 7b; `SCHEMA` 10, an older index is rebuilt automatically).
  - `route` nodes: every route record `{ path, component | redirect | children }` of a router
    config, with nested `children` joined onto their parent's path (`/` + `kid` -> `/kid`), the route
    `name` kept as the node detail. They are searchable (`--symbol /expenses`) and shown as
    `route /expenses`. Objects with a `path` but no component / redirect / children (plain data)
    are ignored.
  - `routes_to` (route -> component): the component given as an imported identifier or a lazy
    `() => import('@/views/X.vue')`, `extracted`; a component we cannot place is `unresolved`.
    `--symbol <Component>` shows `Routed from (n)`, `--symbol <route>` shows `Routes to`.
  - `navigates_to` (code -> route, derived): `router.push` / `router.replace` (a `router`, `$router`
    or a variable from `useRouter()`) with a string, a template literal (`/trip/${id}`), a
    concatenation, or `{ name }` / `{ path }`; and in templates `<RouterLink to>` / `:to=` and
    `$router.push(...)`. An exact path or a route name is `extracted`; a path that only fits a
    pattern (`/trip/42` -> `/trip/:id`) or has a dynamic part is `inferred`; no route is an
    `unresolved` lead. Catch-all routes (`/:pathMatch(.*)*`), external URLs, relative targets and
    other objects' `.push()` never count. Recomputed after every update, so renaming a route turns
    the navigations that used it into leads and deleting the router leaves nothing dangling.
  - `--impact` follows both kinds: changing a view lists the router that loads it, then the code
    that navigates to it.
- Measured: one-file update 7 ms on the fixture (budget 300 ms); DB +4%. Unresolved share: fixture
  16%, this repo 66%.
- Not yet: `name`-only links between nested routes, `router.resolve`, route guards, Nuxt file-based
  routing, `<component :is>`.

## 3.0.0-dev.18

- **Props and emits** (phase 2, step 7a; `SCHEMA` 9, an older index is rebuilt automatically).
  - `prop` / `emit` nodes for every form: `defineProps` / `defineEmits` with a type argument (inline
    object type, call signatures `(e: 'save', x: T): void`, a named `interface`/`type` of the same
    file) or runtime arguments (string array, object), `withDefaults(...)`, and the options-API
    `props:` / `emits:` of `export default {}` / `defineComponent({})`. Ids carry a kind prefix
    (`AppHeader.vue#AppHeader.prop:title`, `...emit:toggle-theme`) so a prop and an event of the
    same name never collide; both are `contains` children of their component and show up in
    `--symbol`.
  - `emits` edges: `emit('save', ...)` in the script and `$emit('save')` in the template, from the
    calling function (or the component) to the declared emit; an undeclared event is an
    `unresolved` lead. These calls are no longer counted as unresolved function calls.
  - `passes_prop` / `listens` (derived, `via` `~link`): for each component tag, `:title=`,
    `v-bind:title=`, `title="..."`, `v-model`, `@toggle-theme=` become edges from the parent to the
    prop / emit the child declares, matched across `kebab-case` / `camelCase`. Attributes the child
    does not declare (`class`, `:key`, native events) add nothing. Works through global
    registration and name-matched components, and is recomputed with the `renders` edges.
  - `--symbol <prop or event>` shows `Used by (n)`: who passes it, who listens, who emits.
- Measured: one-file update 7 ms on the fixture (budget 300 ms); DB +8%. Unresolved share: fixture
  16% (was 21%), this repo 66%.
- Not yet: slots, `provide`/`inject`, `v-bind="obj"`, Svelte, props read in the script
  (`props.title`).

## 3.0.0-dev.17

- **Pinia stores, composables and variables of known origin** (phase 2, step 6; `SCHEMA` 8, an
  older index is rebuilt automatically).
  - **Store members (B4):** `defineStore` in options style (`state` / `getters` / `actions`) and
    setup style (what the setup function returns: `ref` -> state, `computed` -> getter, function
    -> action) become `store_member` nodes (`path#useTripStore.addExpense`, `nodes.detail` =
    state / getter / action), listed by `--symbol` and linked from their store by `contains`.
  - **Where a variable comes from:** `const s = useTripStore()`, `const { a, b: c } = useX()`,
    `const { a } = storeToRefs(s)`, `const f = new Foo()` (and Python `x = Foo()`) are recorded.
    Calls and property reads on such a variable are tied to what they hit, in the script and in
    the template (`ui.toggle()`, `{{ store.total }}`, `v-for="e in store.expenses"`):
    `calls_action` (store action), `reads_state` (state / getter), `calls` to a class method
    (found through `extends` too), all `extracted`; a function a composable returns is `inferred`.
    Pinia's own API (`$patch`...) is `calls_ext`; an unknown method stays an `unresolved` lead.
    This replaces the old "store.add() is unresolved" gap and covers the destructuring and
    `new X()` parts of roadmap C1.
  - **`uses_store` / `uses_composable` (B3):** a call to a Pinia store or to a `useXxx` function.
  - `--impact` follows these edges ("calls store action addExpense at :19"), `--symbol` shows them
    in `Called by`, a new `Used by (n)` for state and stores, and `Tested by`; tests that exercise
    a store action are `tests` edges.
  - These edges are derived (`via` starts with `~`) and recomputed from scratch after every update
    that changed anything, so a renamed action or a deleted store updates its users without
    re-parsing them; nothing dangles.
- Measured: one-file update 8 ms on the fixture (budget 300 ms); DB +10%. Unresolved share: fixture
  21% (was 25%), this repo 66%.
- Not yet: JS built-in methods on expressions (`items.map()`, `x.toFixed()`) are still counted as
  unresolved; `emit()` from `defineEmits` (B2); `this.x` inside store actions.

## 3.0.0-dev.16

- **Vue templates** (phase 2, step 5; `SCHEMA` 7, an older index is rebuilt automatically).
  Needs the optional `pip install tree-sitter-html` (CI installs it; `uccif doctor` mentions it
  when a Vue project lacks it). Without it nothing changes.
  - `renders` edges (B1): component -> component, from the template's tags. A tag is matched
    (`expense-item`, `ExpenseItem`) to the script's imports (`extracted`); to a global
    registration `app.component('BaseButton', BaseButton)` (`extracted`, shown as "global
    registration"); otherwise to the one `.vue` file with that name (`inferred`, "matched by file
    name"); several candidates or none stay `unresolved`. Vue/router built-ins (`RouterView`,
    `Transition`...) and packages are `renders_ext`. `<component :is>` and recursion are skipped.
  - Functions called from the template (B6): `@click="save()"`, `@remove="remove"` (a bare
    handler is a call), `{{ format(x) }}`, `:a="fn(b)"`, `v-if`, `v-for`, with the real line.
    They are call edges from the component node, resolved through the script's imports and
    declarations like any other call; `$emit`/`$t` are ignored.
  - `--impact` follows `renders` too (so changing `BaseButton.vue` lists every component that
    renders it, even without an import), and `--symbol <Component>` shows `Renders (n)` and
    `Rendered by (n)`.
  - Derived edges (global / name / unresolved, `via` starting with `~`) are recomputed after
    every update that changed anything, so adding or removing a registration or a file
    updates them without re-parsing the components.
- Measured: one-file update of a `.vue` file 6 ms (budget 300 ms); DB +10%.
- Known gaps: a component reached through a barrel (`import { Card } from '@/components'`) points
  at the barrel; `ui.toggle()` / destructured `sync()` stay unresolved (B4 / C1); Svelte
  templates are not read.

## 3.0.0-dev.15

- **Structural edges** (phase 2, step 4; `SCHEMA` 6, an older index is rebuilt automatically):
  - `extends` / `implements` (A1): JS/TS classes (`extends`, `implements`, generics dropped,
    `Ns.Base`), TS `interface X extends Y, Z`, and Python `class X(Base, mod.Base)`. The base is
    resolved through the file's imports, the same file, or `import mod` namespaces; bases from
    packages or the language (`Vue`, `Error`, `ValueError`, `Generic`) are `extends_ext` /
    `implements_ext` (known, not repo code); anything else is `unresolved`. Bases imported
    through a barrel get a derived edge (`via`) straight to the defining file, like calls.
    Mixin calls (`extends Mix(Base)`) are skipped.
  - `contains` (A3): file -> top-level symbol and class -> method, so the graph can be walked
    from a file down to its functions. Impact and the graph view still follow only
    imports/calls, so containment never makes a file "depend" on itself.
  - `tests` (A4): for a test file, each resolved call is also a `tests` edge from the test
    (or its enclosing function) to the symbol it exercises, with `file:line`.
    `tests_for` (and so `--impact` "tests to run") also uses them, which catches tests that
    reach the code through a barrel.
- `--symbol` shows, within the 30-line limit: `Extends / implements`, `Subclasses /
  implementations (n)` and `Tested by (n)` with `file:line`.
- The benchmark's unresolved share ignores `contains`/`tests`/`*_ext` edges (they cannot be
  unresolved). Measured: one-file update 5-6 ms, DB +20% (this repo 1.5 -> 1.8 MB).
- Not yet: method calls on expressions (`new Base().run()`) stay unresolved (roadmap C1), so
  tests that only call methods show the class, not the method.

## 3.0.0-dev.14

- **Import resolution rewritten** (phase 2, step 3), now in `uccif_lib/resolve.py`
  (`SCHEMA` 5; an older index is rebuilt automatically).
  - **JS/TS aliases from config (C5):** the nearest `tsconfig.json` / `jsconfig.json`
    (`baseUrl`, `paths`, relative `extends`; comments and trailing commas allowed) and
    `vite.config.*` `resolve.alias` (object form and `{ find, replacement }`, with
    `fileURLToPath(new URL(...))` or `path.resolve(__dirname, ...)`). "Nearest" means the
    folder with a package.json / tsconfig / vite config, so a monorepo package keeps its own
    aliases. With no config `@/` and `~/` still mean `src/`.
  - **Python (C4):** besides the repo root, `src/`, `lib/` and `app/`, package roots declared
    in `pyproject.toml` / `setup.cfg`, the parent of every top-level package (a folder with
    `__init__.py`), and the importing file's own folder (scripts, pytest siblings). This repo
    went from 28 unresolved imports to 1-2% of edges.
  - **Barrels (A2):** `export * from`, `export { a as b } from` (and Python `__init__.py`
    `from .x import y`) are stored as `re_exports` edges. After each update that changed
    anything, derived edges with `via` = the barrel link importers and callers straight to the
    file that defines the name, so `--impact` on `utils/format.ts` finds `ExpenseList.vue`
    ("imports '@/utils' via src/utils/index.ts"), and tests that import through a barrel count
    as tests for the real file. Derived edges are recomputed from scratch each time, so they
    cannot go stale; the direct edge to the barrel stays.
- New `bindings` table (which local name comes from which import) feeds the barrel pass.
- Measured: one-file update 6-7 ms (budget 300 ms; the barrel pass is a few queries on small
  repos, to be re-measured on a real app); DB +10-15%.
- Unresolved share: vue-app 28%, this repo 68% with tree-sitter (method calls on local
  variables, roadmap C1; 1% without it). No remaining import gaps in the fixture.

## 3.0.0-dev.13

- **Unified code graph** (phase 2, step 2): two new tables, written alongside the existing
  ones (`SCHEMA` 4; an older index is rebuilt automatically, and a reader never serves an
  index from another schema).
  - `nodes(id, kind, name, path, line, end_line, scope, precision)`: one `file` node per file
    plus one per symbol. Ids are stable (`path` / `path#Scope.name`), so edges from other
    files survive a re-parse. Node kinds use `_` (`css_var`); `end_line` is filled later.
  - `edges(src_id, dst_id, kind, line, confidence, detail, src_path, dst_path)`. Kinds today:
    `imports`, `calls` (to the callee's symbol node, from the enclosing function's node),
    and `imports_ext` / `calls_ext` for packages and language built-ins (`vue`, `ref()`,
    `print()`, `console.log()`): fully known, just not repo code. `confidence`:
    `extracted` / `inferred` (none yet) / `unresolved` (name known, target not, `dst_id` NULL).
    `src_path`/`dst_path` are kept on each edge so per-file updates and file queries stay
    indexed lookups.
  - Updates keep the graph whole: a re-parsed file re-points incoming edges to its symbols by
    name (or to the file if the symbol is gone); a deleted file turns incoming edges into
    `unresolved` leads instead of dangling ids.
- `--impact`, `--path`, `--symbol` callers, `dependents` and the HTML graph now read `edges`.
  `impact()` takes `kinds` and `min_confidence` (CLI flags come with the query step).
- `index status` adds `Graph: N nodes, M edges (extracted a, inferred b, unresolved c)`;
  `tests/bench_index.py` adds nodes, edges and the unresolved share (warns above 30%).
- Measured (this sandbox): one-file update still 5 ms (budget 300 ms). The DB is about 2.5×
  larger (this repo: 520 → 1300 KB) while old and new tables are both written; a later PR can
  drop the old ones.
- **Unresolved share (reported per the plan):** vue-app fixture 29%, at the 30% limit. The
  remainder are store actions called on a variable (`store.addExpense()`, roadmap B4/C1), test
  globals (`expect`, `it`) and `emit`. This repo: 79%, nearly all method calls on local
  variables (`x.get()`, `con.execute()`), roadmap C1, plus Python absolute imports outside
  `src/`/`lib/`/`app/` (`uccif_lib.*`, roadmap C4), now shown as `unresolved` leads rather than
  as packages.

## 3.0.0-dev.12

- **Code graph, phase 2, step 0** (no change to the plugin's behaviour): groundwork for the
  detailed-graph roadmap.
  - `tests/fixtures/vue-app/`: a fixed Vue 3 + Vite + Pinia + vue-router mini app (24 indexed
    files) with `<script setup>`, props/emits, a composable, two stores (options and setup
    style), lazy routes, a barrel `index.ts`, `@/` imports and CSS variables.
  - `tests/test_fixture_vue_app.py`: pins what the index knows about it today, including the
    known gaps later PRs close (barrel re-exports, `store.action()` calls unresolved).
  - `tests/bench_index.py`: full build, one-file update (budget 300 ms) and no-op update
    timings, DB size and row counts; run by hand, not collected by pytest or CI.
- Baseline (this sandbox, median of 5): fixture 57 ms full build / 4 ms one-file update / 64 KB;
  this repo 107 ms / 4 ms / 520 KB (tree-sitter), 57 ms / 3 ms / 160 KB (regex).

## 3.0.0-dev.11

- **Graph view** (step 4 of the code-graph roadmap): `uccif index graph [--out FILE]
  [--max-nodes N]` writes one self-contained HTML page (no network, no libraries) with the
  most-connected files (default 300) as dots and resolved imports/calls as lines. Click a dot
  for what it uses and what uses it (with the `--impact` command to run next), search by
  name, hide tests or call edges, pan and zoom; light and dark themes.
- The page is written next to the index (outside the repo); where that is read-only (Claude
  Code's Bash sandbox) it goes to the git-ignored `.claude/uccif/.local/`. Nothing tracked is
  touched. Meant for a person to open; Claude keeps using `--impact` / `--path`.
- Known limit (index, not the view): Python absolute imports only resolve from `src/`,
  `lib/`, `app/` or the repo root, so a package under another folder (e.g. `plugins/x/pkg`)
  shows no links.

## 3.0.0-dev.10

- **Graph queries** (step 3 of the code-graph roadmap):
  - `uccif index query --impact <file> [--depth N]` (default 3, max 6): the files that import
    or call into a file, level by level, each as `file:line` with the import and the call that
    link it, plus the tests to run. Breadth-first over import edges and, where tree-sitter
    parsed the file, call edges.
  - `uccif index query --path <A> <B>`: the shortest import/call chain between two files or
    symbols (tries A uses B, then B uses A), one `file:line` hop per line.
  - Both stay within 30 lines (counted "... +N more"), work without tree-sitter (import edges
    only) and read the index read-only like the other queries.
- Imports now store their line number (`SCHEMA` 3; an older index is rebuilt automatically).
- `code-impact-analysis`, `code-impact-analyzer`, `smart-code-search` and the session hint use
  `--impact` / `--path`.

## 3.0.0-dev.9

- **Call graph** (step 2 of the code-graph roadmap). With tree-sitter installed, the index
  also records who calls what in a new `calls` table (`SCHEMA` 2; an old index is rebuilt
  automatically). Each call keeps its enclosing function (`Class.method`), line, and, when it
  can be worked out, the repo file defining the callee: through the file's own imports (named,
  aliased, namespace, Python `from . import`), same-file definitions, and `this.x()` /
  `self.x()`. Everything else is stored unresolved, never guessed.
- `uccif index query --symbol X` now shows `Called by (n)` (resolved) and
  `Possibly called by (receiver unresolved) (n)` with `file:line in caller`, still within the
  30-line limit (callers are capped, references shrink to fit). `index status` shows the
  number of call edges.
- Without tree-sitter nothing changes: no call edges, `git grep` references as before.
- Known limits: calls on variables (`store.add()`) and dynamic calls stay unresolved; a call
  resolved before its target file existed is refreshed only when the caller file is re-parsed.

## 3.0.0-dev.8

- **Optional tree-sitter parsing** for the code index (step 1 of the code-graph roadmap).
  When `tree-sitter`, `tree-sitter-javascript`/`-typescript` and `tree-sitter-python` are
  importable, JS/TS/TSX/Vue/Svelte/Python files get exact symbols (functions, classes, methods
  with their class, arrow-function consts, Pinia `defineStore`, types/interfaces/enums) and
  exact imports (`import`, `export … from`, `require`, dynamic `import()`, `import a, b`),
  stored with precision `ast`. Vue/Svelte parse only `<script>` and keep real line numbers.
- Fallback order is tree-sitter → universal-ctags → regex; without the packages behaviour is
  unchanged. Nothing is installed automatically; `uccif doctor` and `index status` say which
  tool is active. `UCCIF_NO_TREE_SITTER=1` turns it off.
- CI runs the suite a second time with the tree-sitter packages installed.

## 3.0.0-dev.7

- Windows: the Stop hook crashed printing the token line (its emoji cannot be encoded in the
  console's legacy code page), so Windows users never saw it. The CLI now switches
  stdin/stdout/stderr to UTF-8, and hook JSON is written ASCII-escaped. Prompts in
  Vietnamese reach the hooks intact too.

## 3.0.0-dev.6

Found by the Windows CI job:
- Files edited by Claude are recorded with `/` separators on Windows too (they were stored as
  `src\a.ts`, so task file lists and index keys did not match).
- Git output is decoded as UTF-8 everywhere; Windows' locale code page garbled non-ASCII paths.
- Tests: run the launcher with Git Bash (a bare `bash` on Windows can be WSL's launcher), read
  UTF-8 explicitly, and leave a directory before renaming it.

## 3.0.0-dev.5

- `uccif detect` reports LSP status only for languages the plugin configures (TS/JS, Python);
  others (e.g. Vue) go to `no_lsp`, covered by the code index. `/uccif:init` no longer asks
  about installing a server the plugin would not use.
- `/uccif:init` states that `.claude/uccif/` docs and `.gitignore` are meant to be committed
  instead of asking, and leaves unrelated untracked files alone.

## 3.0.0-dev.4

- Works inside Claude Code's Bash sandbox, which denies writes under `~/.claude`:
  - `uccif index query` / `status` open the index read-only (rollback journal instead of
    WAL); the refresh before a query is skipped there, since hooks keep the index current.
  - Task memory and drift state moved to `<project>/.claude/uccif/.local/` (writable in the
    sandbox, git-ignored through `.claude/uccif/.gitignore`). Existing task state is migrated
    automatically at the next session start.
  - `uccif doctor` reports a read-only data dir as INFO, not a failure.
- `doctor` no longer warns about languages the plugin has no LSP config for (e.g. Vue); it
  notes that the code index covers them. Missing bundled servers show the install command.

## 3.0.0-dev.3

- **Code index** (`uccif index query --symbol | --file | --tests-for`, `index status|build`):
  SQLite map of files, symbols, imports and tests, kept outside the repo. Symbols from
  universal-ctags when installed, otherwise per-language regexes; references counted live
  with `git grep`. Every query refreshes changed files first.
- **Automatic upkeep:** SessionStart builds/refreshes the index and checks drift in the
  background; each Edit/Write re-indexes that file; Stop refreshes everything touched outside
  Claude (Bash, the user, git pull). No manual step.
- **Drift detection** (`uccif drift check|show|ack`): new/removed source dirs, dependency and
  build-config changes are handed to Claude on the next prompt with the doc section to update.
- **LSP:** the plugin ships `.lsp.json` for TypeScript/JavaScript and Python. When a project's
  main language has no server installed, Claude offers the install command once per machine.
- Every prompt reminds Claude to search with the index first; skills and agents use it.
- `uccif doctor` reports index status.

## 3.0.0-dev.2

- Windows: the launcher no longer sets `PYTHONPATH` (its `:` separator and `/c/...` paths
  break native Windows Python); it runs `scripts/uccif_main.py`, which sets `sys.path` itself.
- Hooks use the quoted shell form (`"${CLAUDE_PLUGIN_ROOT}/bin/uccif" hook <event>`) instead
  of exec form, because exec-form `args` are unreliable on Windows.
- CI runs on Windows too (experimental, does not fail the run). New manual `smoke` workflow.
- Data-dir fallback picks the core plugin's dir (`uccif-uccif`, or a dir holding the core
  marker), never a sibling plugin such as `uccif-strict-*`.
- The repo's root commit is cached in `meta.json` instead of walking history on every hook.
- PreToolUse calls that skip (every main-agent Bash call) are no longer logged.
- Task state is guarded by a cross-process lock: two sessions on one project can no longer
  overwrite each other or reuse a task id. A stale lock (crashed process) is taken over.
- CORE RULES no longer mention an index that arrives only in 3.2.
- Token line shows billions as `B`.
- `uccif detect` / `doctor` no longer name unconfirmed LSP plugins (Go, Vue).

## 3.0.0-dev.1

- First plugin skeleton: hooks, task memory, token line, logs, `/uccif:init`, 3 agents, tests, CI.
