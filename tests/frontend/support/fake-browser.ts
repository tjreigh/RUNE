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

export interface TimerServices {
  setTimeout: typeof globalThis.setTimeout;
  clearTimeout: typeof globalThis.clearTimeout;
}

export interface ManualTimers extends TimerServices {
  readonly pendingCount: number;
  pendingCountFor: (delay: number) => number;
  hasPending: (delay: number) => boolean;
  runNext: (delay?: number) => void;
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

export function manualTimers(): ManualTimers {
  type TimerHandle = ReturnType<typeof globalThis.setTimeout>;
  const scheduled = new Map<
    TimerHandle,
    { callback: () => void; delay: number }
  >();
  let nextId = 1;
  const timerServices = {
    setTimeout: ((
      callback: () => void,
      delay = 0,
    ): TimerHandle => {
      const handle = nextId++ as unknown as TimerHandle;
      scheduled.set(handle, { callback, delay });
      return handle;
    }) as typeof globalThis.setTimeout,
    clearTimeout: ((handle: TimerHandle | undefined): void => {
      if (handle !== undefined) {
        scheduled.delete(handle);
      }
    }) as typeof globalThis.clearTimeout,
  };
  return {
    ...timerServices,
    get pendingCount(): number {
      return scheduled.size;
    },
    hasPending(delay: number): boolean {
      return Array.from(scheduled.values()).some(
        (timer) => timer.delay === delay,
      );
    },
    pendingCountFor(delay: number): number {
      return Array.from(scheduled.values()).filter(
        (timer) => timer.delay === delay,
      ).length;
    },
    runNext(delay?: number): void {
      const entry = Array.from(scheduled.entries()).find(
        ([, timer]) => delay === undefined || timer.delay === delay,
      );
      if (entry === undefined) {
        throw new Error(
          delay === undefined
            ? "No timer is pending"
            : `No ${delay}ms timer is pending`,
        );
      }
      const [handle, timer] = entry;
      scheduled.delete(handle);
      timer.callback();
    },
  };
}

export function loadApp(
  fetchImpl: FakeFetch,
  initialStoredValues: Iterable<readonly [string, string]> = [],
  timerServices: TimerServices = {
    setTimeout: globalThis.setTimeout,
    clearTimeout: globalThis.clearTimeout,
  },
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
  element("restart");
  element("step-back");
  element("step");
  element("step-over");
  element("step-out");
  element("play");
  element("play-icon", "▶️");
  element("play-label", "Play");
  element("playback-speed-control");
  element("playback-speed", "1");
  element("playback-speed-value");
  element("stop");
  element("debug-status");
  element("examples");
  element("runtime-state");
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
    clearTimeout: timerServices.clearTimeout,
    document: document as unknown as Document,
    fetch: fetchImpl as unknown as typeof globalThis.fetch,
    localStorage: {
      getItem: (key: string) => storedValues.get(key) ?? null,
      setItem: (key: string, value: string) => storedValues.set(key, value),
    } as unknown as Storage,
    setTimeout: timerServices.setTimeout,
  });
  return { document, elements, storedValues };
}

export const waitForDebounce = (): Promise<void> => (
  new Promise((resolve) => setTimeout(resolve, 325))
);

export const flushAsync = (): Promise<void> => (
  new Promise((resolve) => setImmediate(resolve))
);
