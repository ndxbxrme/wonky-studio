export default TurboMini;
export type RenderMode = "microtask" | "raf" | "throttle" | "debounce" | "idle";
export type RenderStrategyOptions = any;
export type Controller = (params?: string[]) => (Promise<any> | any);
export type Middleware = (ctx: Context) => (boolean | void | Promise<boolean | void>);
export type TemplateRegistrar = (name: string, text: string) => TurboMiniApp;
export type TemplateRenderer = (name: string, data?: any, opts?: {
    helpers?: Record<string, HelperFn>;
}) => string;
export type ComponentDefiner = (name: string, def: {
    template: string;
    controller?: Controller;
}) => TurboMiniApp;
export type ControllerRegistrar = (name: string, fn: Controller) => TurboMiniApp;
export type MiddlewareAdder = (fn: Middleware) => TurboMiniApp;
export type TemplateFetcher = (names: string[], path?: string) => Promise<void[]>;
export type Context = {
    page: string;
    params: string[];
    data: any;
};
export type HelperFn = (value: any, meta: {
    data?: any;
    stack?: any[];
}) => any;
export type TurboMiniApp = any;
/** @packageDocumentation
 * TurboMini — tiny dependency-free SPA micro-framework.
 * JSDoc types are emitted to .d.ts via TypeScript.
 */
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
export function TurboMini(basePath?: string): TurboMiniApp;
