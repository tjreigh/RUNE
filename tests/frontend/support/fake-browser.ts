import { startRuneRepl } from "../../../frontend/src/repl.js";

type FakeListener = (event: Record<string, unknown>) => unknown;

export class FakeElementStore extends Map<string, FakeElement> {
  override get(id: string): FakeElement {
    const element = super.get(id);
    if (element === undefined) {
      throw new Error(`Missing fake element: ${id}`);
    }
    return element;
  }
}

export class FakeElement {
  value: string;
  textContent = "";
  innerHTML = "";
  className = "";
  readonly listeners = new Map<string, FakeListener>();
  children: FakeElement[] = [];
  selectionStart = 0;
  selectionEnd = 0;
  scrollTop = 0;
  scrollLeft = 0;
  readonly dataset: Record<string, string> = {};
  disabled = false;
  hidden = false;
  tabIndex = 0;
  readonly attributes = new Map<string, string>();
  readonly classes = new Set<string>();
  readonly classList: {
    toggle: (name: string, force?: boolean) => void;
  };

  constructor(value = "") {
    this.value = value;
    this.classList = {
      toggle: (name: string, force?: boolean) => {
        if (force) {
          this.classes.add(name);
        } else {
          this.classes.delete(name);
        }
      },
    };
  }

  addEventListener(kind: string, listener: FakeListener): void {
    this.listeners.set(kind, listener);
  }

  dispatch(
    kind: string,
    event: Record<string, unknown> = {},
  ): unknown {
    return this.listeners.get(kind)?.(event);
  }

  replaceChildren(...children: FakeElement[]): void {
    this.children = children;
    this.textContent = "";
  }

  append(child: FakeElement): void {
    this.children.push(child);
  }

  setAttribute(name: string, value: string): void {
    this.attributes.set(name, value);
  }

  getAttribute(name: string): string | null {
    return this.attributes.get(name) ?? null;
  }

  setSelectionRange(start: number, end: number): void {
    this.selectionStart = start;
    this.selectionEnd = end;
  }

  focus(): void {}
}

export interface FakeResponse<T = unknown> {
  ok: boolean;
  status: number;
  json: () => Promise<T>;
  text: () => Promise<string>;
}

export interface FakeRequestOptions {
  body?: string;
  signal: AbortSignal;
}

export type FakeFetch = (
  url: string,
  options: FakeRequestOptions,
) => Promise<FakeResponse>;

export interface RecordedRequest {
  url: string;
  options: FakeRequestOptions;
}

export function deferred<T = FakeResponse>(): {
  promise: Promise<T>;
  resolve: (value: T) => void;
} {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((settle) => {
    resolve = settle;
  });
  return { promise, resolve };
}

export function response<T>(body: T, status = 200): FakeResponse<T> {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    text: async () => (
      typeof body === "string" ? body : JSON.stringify(body)
    ),
  };
}

export function loadApp(
  fetchImpl: FakeFetch,
  initialStoredValues: Iterable<readonly [string, string]> = [],
): {
  document: {
    documentElement: FakeElement;
    getElementById: (id: string) => FakeElement;
    querySelectorAll: () => FakeElement[];
    createElement: () => FakeElement;
  };
  elements: FakeElementStore;
  storedValues: Map<string, string>;
} {
  const elements = new FakeElementStore();
  const storedValues = new Map<string, string>(initialStoredValues);
  const element = (id: string, value = ""): FakeElement => {
    const created = new FakeElement(value);
    elements.set(id, created);
    return created;
  };
  element("source", "1");
  element("editor-frame");
  element("editor-theme", "classic-dark");
  element("page-theme", "system");
  element("highlighting");
  element("highlighting-content");
  element("trace-highlighting");
  element("trace-highlighting-content");
  element("source-position");
  element("validation-status");
  element("output");
  element("run");
  element("debug");
  element("reset");
  element("step-back");
  element("step");
  element("step-over");
  element("step-out");
  element("stop");
  element("debug-status");
  element("examples");
  element("chaos-level");
  element("inspector-state");
  element("inspector-events");
  element("inspector-stats");
  element("inspector-context");

  const document = {
    documentElement: new FakeElement(),
    getElementById: (id: string) => elements.get(id),
    querySelectorAll: () => [],
    createElement: () => new FakeElement(),
  };
  startRuneRepl({
    AbortController,
    clearTimeout,
    document: document as unknown as Document,
    fetch: fetchImpl as unknown as typeof globalThis.fetch,
    localStorage: {
      getItem: (key: string) => storedValues.get(key) ?? null,
      setItem: (key: string, value: string) => storedValues.set(key, value),
    } as unknown as Storage,
    setTimeout,
  });
  return { document, elements, storedValues };
}

export const waitForDebounce = (): Promise<void> => (
  new Promise((resolve) => setTimeout(resolve, 325))
);

export const flushAsync = (): Promise<void> => (
  new Promise((resolve) => setImmediate(resolve))
);
