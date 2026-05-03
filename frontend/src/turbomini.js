/** @packageDocumentation
 * TurboMini — tiny dependency-free SPA micro-framework.
 * JSDoc types are emitted to .d.ts via TypeScript.
 */

// ─────────────────────────────── Core typedefs ──────────────────────────────

/** Render scheduling modes. */
/** @typedef {"microtask"|"raf"|"throttle"|"debounce"|"idle"} RenderMode */

/** Options for configuring the render scheduler. */
/** @typedef {Object} RenderStrategyOptions */
/** @property {RenderMode} [mode="microtask"] Scheduling mode. */
/** @property {number} [interval=16] Interval in ms for throttle/debounce/idle. */
/** @property {boolean} [leading=false] Throttle leading-edge behavior. */

/** A route controller. Returns data sync or async. */
/** @typedef {(params?: string[]) => (Promise<any> | any)} Controller */

/** Middleware run before navigation; return false to cancel. */
/** @typedef {(ctx: Context) => (boolean|void|Promise<boolean|void>)} Middleware */

/** Register/compile a template. */
/** @typedef {(name: string, text: string) => TurboMiniApp} TemplateRegistrar */

/** Render a template to string. */
/** @typedef {(name: string, data?: any, opts?: {helpers?: Record<string, HelperFn>}) => string} TemplateRenderer */

/** Define a component (template + optional controller). */
/** @typedef {(name: string, def: { template: string, controller?: Controller }) => TurboMiniApp} ComponentDefiner */

/** Register a route controller. */
/** @typedef {(name: string, fn: Controller) => TurboMiniApp} ControllerRegistrar */

/** Add a middleware function. */
/** @typedef {(fn: Middleware) => TurboMiniApp} MiddlewareAdder */

/** Fetch templates from the network and register them. */
/** @typedef {(names: string[], path?: string) => Promise<void[]>} TemplateFetcher */

/** Routing context. */
/** @typedef {{page: string, params: string[], data: any}} Context */

/** Template helper signature. */
/** @typedef {(value: any, meta: {data?: any, stack?: any[]}) => any} HelperFn */

/** The TurboMini application API. */
/** @typedef {Object} TurboMiniApp */
/** @property {TemplateRegistrar} template */
/** @property {TemplateRenderer} $t */
/** @property {ComponentDefiner} defineComponent */
/** @property {ControllerRegistrar} controller */
/** @property {() => Promise<void>} start */
/** @property {(route: string) => void} goto */
/** @property {() => void} refresh */
/** @property {() => void} refreshNow */
/** @property {(opts?: RenderStrategyOptions) => void} setRenderStrategy */
/** @property {Context} context */
/** @property {TemplateFetcher} fetchTemplates */
/** @property {TemplateFetcher} prefetchTemplates */
/** @property {(name: string, fn: HelperFn) => TurboMiniApp} registerHelper */
/** @property {(name: string) => TurboMiniApp} unregisterHelper */
/** @property {() => string[]} listHelpers */
/** @property {() => {routes: string[], templates: Record<string, Function>, helpers: string[], mode: "history"|"hash", renderStrategy: RenderMode}} inspect */
/** @property {boolean} useHash */
/** @property {(type: string, handler: EventListener, opts?: any) => TurboMiniApp} on */
/** @property {(type: string, handler: EventListener, opts?: any) => TurboMiniApp} off */
/** @property {(el: Element, type: string, handler: EventListener, opts?: any) => (() => void)} listen */
/** @property {(fn: (app: TurboMiniApp) => any) => Promise<TurboMiniApp>} run */
/** @property {(e: unknown) => void} errorHandler */
/** @property {() => void} invalidate */

/**
 * Create a TurboMini application.
 * @param {string} [basePath="/"] "/" for history mode, "#" for hash routing, or a sub-path like "/app".
 * @returns {TurboMiniApp}
 */

const TurboMini = (basePath = "/") => {
  // ---- Routing mode ---------------------------------------------------------
  const useHash = basePath === "#";

  // ---- Internal registries --------------------------------------------------
  const controllers = Object.create(null);
  const templates = Object.create(null);
  const helpers = Object.create(null);
  const middleware = [];

  // ---- Context --------------------------------------------------------------
  const ctx = { page: "default", params: [], data: null };

  // ---- Small utils ----------------------------------------------------------
  const hasDOM =
    typeof window !== "undefined" &&
    typeof document !== "undefined" &&
    !!document.querySelector;

  const win = hasDOM ? window : /** @type {any} */ ({});
  const doc = hasDOM ? document : /** @type {any} */ ({});

  /** query helper; returns {} when no DOM so tests don't explode */
  const $ = (s, e, a) =>
    hasDOM ? (e || doc)["querySelector" + (a ? "All" : "")](s) || {} : {};

  /** event helpers; no-ops in Node */
  const on = (t, f, o) => {
    if (hasDOM && win.addEventListener) win.addEventListener(t, f, o);
  };
  const off = (t, f, o) => {
    if (hasDOM && win.removeEventListener) win.removeEventListener(t, f, o);
  };

  // Escape HTML
  const escapeHtml = (v) =>
    String(v)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");

  const get = (obj, path) =>
    path === "." || path === "this"
      ? obj
      : path.split(".").reduce((o, k) => (o == null ? undefined : o[k]), obj);

  // ---- Helpers (internal registration during boot) --------------------------
  /** @internal */
  const _registerHelper = (name, fn) => {
    if (!/^[A-Za-z_][\w$]*$/.test(name))
      throw new Error(`Invalid helper name: ${name}`);
    if (typeof fn !== "function")
      throw new TypeError("Helper must be a function");
    helpers[name] = fn;
  };
  /** @internal */
  const _unregisterHelper = (name) => {
    delete helpers[name];
  };

  // Built-in helpers (use internal register to avoid TDZ with `app`)
  _registerHelper("json", (obj) => {
    const s = JSON.stringify(obj ?? null);
    return s
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  });
  _registerHelper("classList", (obj) => {
    if (obj && typeof obj === "object" && !Array.isArray(obj))
      return Object.entries(obj)
        .filter(([, v]) => !!v)
        .map(([k]) => k)
        .join(" ");
    if (Array.isArray(obj)) return obj.filter(Boolean).join(" ");
    return String(obj ?? "");
  });
  _registerHelper("date", (iso, { data }) =>
    new Date(iso).toLocaleDateString(data?.locale || "en-GB"),
  );
  _registerHelper("number", (n, { data }) =>
    new Intl.NumberFormat(data?.locale || "en-GB").format(n),
  );

  // ---- Templating compiler --------------------------------------------------
  /** @internal */
  const parseExpr = (src) => {
    const parts = src.trim().split(/\s+/);
    return parts.length === 1
      ? { type: "path", path: parts[0] }
      : {
          type: "helper",
          name: parts[0],
          args: parts.slice(1).map((p) => ({ type: "path", path: p })),
        };
  };

  /** @internal */
  const evalExpr = (expr, data, stack, H) => {
    if (expr.type === "path") return get(data, expr.path);
    const h = H[expr.name];
    if (!h) throw new Error(`Unknown helper: ${expr.name}`);
    const args = expr.args.map((a) => evalExpr(a, data, stack, H));
    return h(...args, { data, stack });
  };

  /** @internal */
  const tokenize = (tpl) => {
    const tokens = [];
    let i = 0;
    const re =
      /\{\{\{([\s\S]+?)\}\}\}|\{\{(#each|#if|\/each|\/if|>|\s*)([\s\S]*?)\}\}/g;
    let m;
    while ((m = re.exec(tpl))) {
      if (m.index > i) tokens.push({ t: "text", v: tpl.slice(i, m.index) });
      if (m[1]) tokens.push({ t: "raw", v: m[1].trim() });
      else {
        const kind = m[2],
          body = m[3].trim();
        if (kind === "#each") tokens.push({ t: "eachStart", v: body });
        else if (kind === "/each") tokens.push({ t: "eachEnd" });
        else if (kind === "#if") tokens.push({ t: "ifStart", v: body });
        else if (kind === "/if") tokens.push({ t: "ifEnd" });
        else if (kind === ">") tokens.push({ t: "partial", v: body });
        else tokens.push({ t: "esc", v: (kind + " " + body).trim() });
      }
      i = re.lastIndex;
    }
    if (i < tpl.length) tokens.push({ t: "text", v: tpl.slice(i) });
    return tokens;
  };

  /** @internal */
  const buildAst = (tokens) => {
    const root = { t: "block", children: [] };
    const stack = [root];
    for (const tok of tokens) {
      if (tok.t === "eachStart" || tok.t === "ifStart") {
        const node =
          tok.t === "eachStart"
            ? { t: "each", v: tok.v, children: [] }
            : { t: "if", v: tok.v, children: [] };
        stack.at(-1).children.push(node);
        stack.push(node);
      } else if (tok.t === "eachEnd" || tok.t === "ifEnd") {
        const want = tok.t === "eachEnd" ? "each" : "if";
        if (stack.at(-1).t !== want) throw new Error(`Unmatched {{/${want}}}`);
        stack.pop();
      } else {
        stack.at(-1).children.push(tok);
      }
    }
    if (stack.length !== 1) throw new Error("Unclosed section");
    return root;
  };

  /** @internal */
  const parsePartial = (src) => {
    const [name, ...rest] = src.split(/\s+/);
    const args = Object.create(null);
    if (rest.length === 1 && rest[0] === ".")
      args["."] = { type: "path", path: "." };
    else
      for (const pair of rest) {
        const m = pair.match(/^([\w.$]+)=(.+)$/);
        if (m) args[m[1]] = parseExpr(m[2]);
      }
    return { name, args };
  };

  /** @internal */
  const compileTemplate = (tpl) => {
    const ast = buildAst(tokenize(tpl));
    const renderNode = (node, data, stack, env) => {
      const H = env.helpers;
      switch (node.t) {
        case "block":
          return node.children
            .map((n) => renderNode(n, data, stack, env))
            .join("");
        case "text":
          return node.v;
        case "raw":
          return String(get(data, node.v) ?? "");
        case "esc": {
          const ex = parseExpr(node.v);
          const v = evalExpr(ex, data, stack, H);
          return escapeHtml(v ?? "");
        }
        case "partial": {
          const { name, args } = parsePartial(node.v);
          const render = env.templates[name];
          if (!render) throw new Error(`Partial "${name}" not found.`);
          let pd = {};
          for (const [k, ex] of Object.entries(args)) {
            if (k === ".") pd = evalExpr(ex, data, stack, H);
            else pd[k] = evalExpr(ex, data, stack, H);
          }
          return render(pd == null ? {} : pd, env);
        }
        case "each": {
          const m = node.v.match(/^(.+?)(?:\s+as\s+([A-Za-z_$][\w$]*))?$/);
          const expr = parseExpr(m[1]);
          const alias = m[2] || null;
          const arr = evalExpr(expr, data, stack, H) || [];
          let out = "";
          for (let i = 0; i < arr.length; i++) {
            const item = arr[i];
            const childData = alias
              ? Object.assign(Object.create(data), { [alias]: item, index: i })
              : item;
            out += node.children
              .map((n) => renderNode(n, childData, [...stack, item], env))
              .join("");
          }
          return out;
        }
        case "if": {
          const cond = !!evalExpr(parseExpr(node.v), data, stack, H);
          if (!cond) return "";
          return node.children
            .map((n) => renderNode(n, data, stack, env))
            .join("");
        }
        default:
          return "";
      }
    };
    return (data, env) => renderNode(ast, data || {}, [data], env);
  };

  // Runtime render glue
  /**
   * Register and compile a string template.
   * @type {TemplateRegistrar}
   * @example app.template("home", "<h1>{{title}}</h1>");
   */
  const template = (name, text) => {
    if (typeof name !== "string" || typeof text !== "string")
      throw new TypeError("template(name, text) requires strings");
    templates[name] = compileTemplate(text);
    return app;
  };

  /**
   * Render a registered template by name.
   * @type {TemplateRenderer}
   * @example const html = app.$t("home", { title: "Welcome" });
   */
  const $t = (name, data, opts = {}) => {
    const render = templates[name];
    if (!render) throw new Error(`Template "${name}" not found.`);
    const H = Object.assign(Object.create(null), helpers, opts.helpers || {});
    return render(data, { templates, helpers: H });
  };

  /**
   * Define a component by registering its template and optional controller.
   * @type {ComponentDefiner}
   */
  const defineComponent = (name, { template: tpl, controller: c }) => {
    template(name, tpl);
    if (typeof c === "function") app.controller(name, c);
    return app;
  };

  // ---- Render scheduler -----------------------------------------------------
  /** @type {RenderMode} */
  let _mode = "microtask"; // 'microtask' | 'raf' | 'throttle' | 'debounce' | 'idle'
  let _interval = 16; // ms (throttle/debounce/idle timeout)
  let _leading = false; // throttle leading edge
  let _pending = false;
  let _timer = null;
  let _rafId = null;
  let _idleId = null;

  // indirection so the scheduler uses the public method once app exists
  let _callRefresh = () => refreshNow(); // will be rebound after app creation

  /**
   * Configure the render scheduler.
   * @param {RenderStrategyOptions} [options]
   */
  const setRenderStrategy = ({ mode, interval, leading } = {}) => {
    if (mode) _mode = mode;
    if (typeof interval === "number") _interval = Math.max(0, interval);
    if (typeof leading === "boolean") _leading = leading;
    if (_timer) {
      clearTimeout(_timer);
      _timer = null;
    }
    if (_rafId != null && hasDOM) {
      cancelAnimationFrame(_rafId);
      _rafId = null;
    }
    if (_idleId != null && hasDOM && "cancelIdleCallback" in win) {
      cancelIdleCallback(_idleId);
      _idleId = null;
    }
  };

  const _scheduleMicrotask = () => {
    if (_pending) return;
    _pending = true;
    queueMicrotask(() => {
      _pending = false;
      _callRefresh();
    });
  };

  const _scheduleRAF = () => {
    if (!hasDOM) return _scheduleMicrotask();
    if (_rafId != null) return;
    _rafId = win.requestAnimationFrame(() => {
      _rafId = null;
      _callRefresh();
    });
  };

  const _scheduleThrottle = () => {
    if (_timer) return;
    if (_leading && !_pending) {
      _pending = true;
      _callRefresh();
    }
    _timer = setTimeout(() => {
      _timer = null;
      if (!_leading || _pending) _callRefresh();
      _pending = false;
    }, _interval);
  };

  const _scheduleDebounce = () => {
    clearTimeout(_timer);
    _timer = setTimeout(() => _callRefresh(), _interval);
  };

  const _scheduleIdle = () => {
    if (!hasDOM || !("requestIdleCallback" in win)) return _scheduleMicrotask();
    if (_idleId != null) cancelIdleCallback(_idleId);
    _idleId = requestIdleCallback(
      () => {
        _idleId = null;
        _callRefresh();
      },
      { timeout: _interval || 50 },
    );
  };

  /** @internal */
  const invalidate = () => {
    switch (_mode) {
      case "raf":
        return _scheduleRAF();
      case "throttle":
        return _scheduleThrottle();
      case "debounce":
        return _scheduleDebounce();
      case "idle":
        return _scheduleIdle();
      case "microtask":
      default:
        return _scheduleMicrotask();
    }
  };

  // ---- Patch / diff against <page> root ------------------------------------
  let lastHTML = null;

  /** @internal */
  const getByPath = (path, root) => {
    let el = root;
    for (const idx of path) {
      if (!el.children || idx >= el.children.length)
        throw new Error("Invalid path");
      el = el.children[idx];
    }
    return el;
  };

  /** @internal */
  const walk = (path, liveRoot, v1root, v2root) => {
    const a = getByPath(path, v1root);
    const b = getByPath(path, v2root);
    const live = getByPath(path, liveRoot);

    const sameOuter = a.outerHTML === b.outerHTML;
    const sameInner = a.innerHTML === b.innerHTML;

    const syncAttrs = () => {
      if (!sameOuter) {
        for (const at of [...live.attributes])
          if (!["value", "checked"].includes(at.name))
            live.removeAttribute(at.name);
        for (const at of [...b.attributes]) {
          if (at.name === "value") live.value = at.value;
          else if (at.name === "checked") live.checked = at.value;
          else live.setAttribute(at.name, at.value);
        }
      }
    };

    if (sameInner && !sameOuter) {
      syncAttrs();
      return;
    }

    if (!sameInner) {
      syncAttrs();
      const tagsA = [...a.children].map((c) => c.tagName).join("");
      const tagsB = [...b.children].map((c) => c.tagName).join("");
      if (tagsA === tagsB && tagsA.length) {
        for (let i = 0; i < a.children.length; i++)
          walk([...path, i], liveRoot, v1root, v2root);
      } else {
        live.innerHTML = b.innerHTML;
      }
    }
  };

  // The *actual* renderer body
  /** @internal */
  const _doActualRefresh = () => {
    if (!hasDOM) return;
    try {
      const pageEl = $("page");
      if (!pageEl || !("innerHTML" in pageEl))
        throw new Error("<page> element not found.");
      const nextHTML = $t(ctx.page, ctx.data);
      if (lastHTML == null) {
        pageEl.innerHTML = nextHTML;
      } else {
        const v1 = doc.createElement("page");
        v1.innerHTML = lastHTML;
        const v2 = doc.createElement("page");
        v2.innerHTML = nextHTML;
        walk([], pageEl, v1, v2);
      }
      lastHTML = nextHTML;
    } catch (e) {
      app.errorHandler?.(e);
    }
  };

  /**
   * Immediate render of the current page.
   * @returns {void}
   */
  const refreshNow = () => _doActualRefresh(); // immediate
  /**
   * Schedule a render according to the current strategy.
   * @returns {void}
   */
  const refresh = () => invalidate(); // scheduled (back-compat name)

  // ---- Router ---------------------------------------------------------------
  const normalizeRoute = () => {
    let raw = useHash
      ? (location.hash || "#/").replace(/^#/, "")
      : location.pathname;
    if (!raw.startsWith("/")) raw = "/" + raw;
    if (raw.length > 1 && raw.endsWith("/")) raw = raw.slice(0, -1);
    if (basePath !== "/" && basePath !== "#" && raw.startsWith(basePath))
      raw = raw.slice(basePath.length) || "/";
    const page = Object.keys(templates).sort((a,b) => a.length > b.length ? -1 : 1).find(key => raw.indexOf(key)===1) || "default";
    raw = raw.replace(page, 'page');
    const parts = raw.split("/").filter(Boolean);
    const params = parts.slice(1);
    return { page, params };
  };

  const applyMiddleware = async () => {
    for (const fn of middleware) if ((await fn(ctx)) === false) return false;
    return true;
  };

  /**
   * Start the router and render the initial route.
   * @returns {Promise<void>}
   */
  const start = async () => {
    try {
      await ctx.data?.unload?.();

      const { page, params } = normalizeRoute();
      ctx.page = page;
      ctx.params = params;

      if (!(await applyMiddleware())) return;

      ctx.data = controllers[ctx.page]
        ? await controllers[ctx.page](ctx.params)
        : null;

      refreshNow(); // render immediately after navigation

      await ctx.data?.postLoad?.();
      if (hasDOM) (win.scrollRoot || doc.body).scrollIntoView();
    } catch (e) {
      app.errorHandler?.(e);
    }
  };

  /**
   * Navigate to a route (e.g., "/profile/1").
   * @param {string} route
   * @returns {void}
   */
  const goto = (route) => {
    if (!route.startsWith("/")) route = "/" + route;
    if (useHash) {
      if (location.hash !== "#" + route) location.hash = route;
      else start();
    } else {
      const fullRoute = basePath === "/" ? route : basePath + route;
      if (location.pathname !== fullRoute) history.pushState({}, "", fullRoute);
      start();
    }
  };

  on("popstate", start);
  on("hashchange", () => {
    if (useHash) start();
  });
  if (hasDOM)
    on("click", (e) => {
      const a = e.target.closest ? e.target.closest("a") : null;
      if (!a) return;
      const href = a.getAttribute("href");
      if (!href || !href.startsWith("/") || (a.target && a.target !== "_self"))
        return;
      e.preventDefault();
      goto(href);
    });

  // ---- Controllers & middleware --------------------------------------------
  /**
   * Register a route controller.
   * @type {ControllerRegistrar}
   */
  const controller = (name, fn) => {
    if (typeof fn !== "function")
      throw new TypeError(`Controller "${name}" must be a function.`);
    controllers[name] = fn;
    return app;
  };

  /**
   * Add a middleware function executed before navigation.
   * @type {MiddlewareAdder}
   */
  const addMiddleware = (fn) => {
    if (typeof fn !== "function")
      throw new TypeError("Middleware must be a function.");
    middleware.push(fn);
    return app;
  };

  // Optional: fetch templates from /components/
  /**
   * Fetch templates from the network and register them.
   * @type {TemplateFetcher}
   */
  const fetchTemplates = (names, path = "/components/") =>
    Promise.all(
      names.map(async (name) => {
        const res = await fetch(`${path}${name}.html`);
        if (!res.ok)
          throw new Error(
            `Failed to fetch template "${name}": ${res.status} ${res.statusText}`,
          );
        template(name, await res.text());
      }),
    );
  /**
   * Alias of fetchTemplates.
   * @type {TemplateFetcher}
   */
  const prefetchTemplates = (names, path) => fetchTemplates(names, path);

  // ---- Public API -----------------------------------------------------------
  const app = {
    // templating
    template,
    $t,
    defineComponent,

    // helpers (chainable public wrappers)
    registerHelper: (name, fn) => (_registerHelper(name, fn), app),
    unregisterHelper: (name) => (_unregisterHelper(name), app),
    listHelpers: () => Object.keys(helpers),

    // routing & lifecycle
    start,
    goto,
    refresh: refresh, // scheduled render (back-compat)
    refreshNow, // immediate render
    setRenderStrategy, // configure scheduler
    controller,
    addMiddleware,
    fetchTemplates,
    prefetchTemplates,

    // state & context
    context: ctx,

    // utilities
    $,
    useHash,
    errorHandler: (e) => console.error("[TurboMini]", e),
    run: async (fn) => (await fn(app), app),
    inspect: () => ({
      routes: Object.keys(controllers),
      templates: { ...templates },
      helpers: Object.keys(helpers),
      mode: /** @type {"history"|"hash"} */ (useHash ? "hash" : "history"),
      renderStrategy: _mode,
    }),
    invalidate, // explicit scheduled render
    /** Add a window-level event listener. Chainable.
     * @type {(type: string, handler: EventListener, opts?: any) => TurboMiniApp} */
    on: (type, handler, opts) => {
      on(type, handler, opts);
      return app;
    },
    /** Remove a window-level event listener. Chainable.
     * @type {(type: string, handler: EventListener, opts?: any) => TurboMiniApp} */
    off: (type, handler, opts) => {
      off(type, handler, opts);
      return app;
    },
    /** Listen on an element; returns a disposer.
     * @type {(el: Element, type: string, handler: EventListener, opts?: any) => (() => void)} */
    listen: (el, type, handler, opts) => {
      if (!el || !el.addEventListener) return () => {};
      el.addEventListener(type, handler, opts);
      return () => el.removeEventListener(type, handler, opts);
    },
  };

  // make scheduler use the public refreshNow (so tests can monkey-patch it)
  _callRefresh = () => app.refreshNow();

  return app;
};

export { TurboMini };
export default TurboMini;
