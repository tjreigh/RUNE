const RUNE_KEYWORDS = new Set([
  "if",
  "elif",
  "else",
  "while",
  "for",
  "from",
  "to",
  "step",
  "break",
  "continue",
  "function",
  "return",
  "end",
  "and",
  "or",
  "not",
]);

const MULTI_CHARACTER_OPERATORS = [
  "**",
  "<<",
  ">>",
  "<=",
  ">=",
  "==",
  "!=",
];

function escapeHtml(text: string): string {
  return text
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function preserveTrailingNewline(source: string, markup: string): string {
  // A trailing newline otherwise collapses in a backdrop and makes the
  // textarea and mirrored layer disagree about their scroll height.
  return source.endsWith("\n") ? `${markup} ` : markup;
}

function highlightedToken(kind: string, text: string): string {
  return `<span class="tok-${kind}">${escapeHtml(text)}</span>`;
}

function matchAt(
  source: string,
  offset: number,
  pattern: RegExp,
): string | null {
  return source.slice(offset).match(pattern)?.[0] ?? null;
}

export function highlightRune(source: string): string {
  let offset = 0;
  let markup = "";
  let expectsFunctionName = false;

  while (offset < source.length) {
    const rest = source.slice(offset);
    const character = rest[0]!;

    const whitespace = matchAt(source, offset, /^[\s]+/u);
    if (whitespace !== null) {
      markup += escapeHtml(whitespace);
      offset += whitespace.length;
      continue;
    }

    if (character === "#") {
      const newline = source.indexOf("\n", offset);
      const end = newline === -1 ? source.length : newline;
      markup += highlightedToken("comment", source.slice(offset, end));
      offset = end;
      expectsFunctionName = false;
      continue;
    }

    if (character === '"') {
      const closingQuote = source.indexOf('"', offset + 1);
      const end = closingQuote === -1 ? source.length : closingQuote + 1;
      const literal = source.slice(offset, end);
      markup += highlightedToken("string", literal);
      offset = end;
      expectsFunctionName = false;
      continue;
    }

    const prefixedNumber = matchAt(
      source,
      offset,
      /^0[bBoOxX][\p{L}\p{N}_]*/u,
    );
    if (prefixedNumber !== null) {
      markup += highlightedToken("number", prefixedNumber);
      offset += prefixedNumber.length;
      expectsFunctionName = false;
      continue;
    }

    const decimalNumber = matchAt(source, offset, /^\p{Nd}+/u);
    if (decimalNumber !== null) {
      markup += highlightedToken("number", decimalNumber);
      offset += decimalNumber.length;
      expectsFunctionName = false;
      continue;
    }

    const identifier = matchAt(
      source,
      offset,
      /^[\p{L}_][\p{L}\p{N}_]*/u,
    );
    if (identifier !== null) {
      let kind = "identifier";
      if (identifier === "chaos") {
        kind = "directive";
      } else if (RUNE_KEYWORDS.has(identifier)) {
        kind = "keyword";
      } else {
        const followingSource = source.slice(offset + identifier.length);
        if (expectsFunctionName || /^\s*\(/u.test(followingSource)) {
          kind = "function";
        }
      }
      markup += highlightedToken(kind, identifier);
      offset += identifier.length;
      expectsFunctionName = identifier === "function";
      continue;
    }

    if (character === "@") {
      markup += highlightedToken("directive", character);
      ++offset;
      expectsFunctionName = false;
      continue;
    }

    const operator = MULTI_CHARACTER_OPERATORS.find(
      (candidate) => rest.startsWith(candidate),
    ) ?? (/[+\-*/%~&|^<>=!]/u.test(character) ? character : null);
    if (operator !== null) {
      markup += highlightedToken("operator", operator);
      offset += operator.length;
      expectsFunctionName = false;
      continue;
    }

    if (/[(),]/u.test(character)) {
      markup += highlightedToken("punctuation", character);
      ++offset;
      continue;
    }

    const numericCodePoint = source.codePointAt(offset);
    if (numericCodePoint === undefined) {
      break;
    }
    const codePoint = String.fromCodePoint(numericCodePoint);
    markup += escapeHtml(codePoint);
    offset += codePoint.length;
    expectsFunctionName = false;
  }

  return preserveTrailingNewline(source, markup);
}

/** Convert RUNE's Unicode code-point columns to textarea UTF-16 offsets. */
export function sourceOffsetAtPosition(
  source: string,
  position: { line: number; column: number },
): number {
  let line = 1;
  let column = 1;
  let offset = 0;

  for (const character of source) {
    if (line === position.line && column === position.column) {
      return offset;
    }
    offset += character.length;
    if (character === "\n") {
      ++line;
      column = 1;
    } else {
      ++column;
    }
  }
  return offset;
}

/**
 * Mirror source text with only the active trace span visibly marked.
 *
 * This markup belongs in its own editor layer. Syntax highlighting remains
 * untouched, so stepping never rebuilds or annotates token markup.
 */
export function highlightActiveTraceSpan(
  source: string,
  span: { start: { line: number; column: number }; end: {
    line: number;
    column: number;
  } } | null,
): string {
  if (span === null) {
    return preserveTrailingNewline(source, escapeHtml(source));
  }
  const start = sourceOffsetAtPosition(source, span.start);
  const end = Math.max(start, sourceOffsetAtPosition(source, span.end));
  const activeSource = source.slice(start, end);
  const marked = activeSource.length === 0 ? " " : escapeHtml(activeSource);
  return preserveTrailingNewline(
    source,
    [
      escapeHtml(source.slice(0, start)),
      `<span class="trace-active-source">${marked}</span>`,
      escapeHtml(source.slice(end)),
    ].join(""),
  );
}

export function scrollTopToRevealLine({
  line,
  scrollTop,
  viewportHeight,
  lineHeight,
  paddingTop,
}: {
  line: number;
  scrollTop: number;
  viewportHeight: number;
  lineHeight: number;
  paddingTop: number;
}): number {
  if (viewportHeight <= 0 || lineHeight <= 0) {
    return scrollTop;
  }
  const lineTop = paddingTop + (Math.max(1, line) - 1) * lineHeight;
  const lineBottom = lineTop + lineHeight;
  const context = Math.min(lineHeight * 2, viewportHeight / 3);
  if (lineTop < scrollTop + context) {
    return Math.max(0, lineTop - context);
  }
  if (lineBottom > scrollTop + viewportHeight - context) {
    return Math.max(0, lineBottom - viewportHeight + context);
  }
  return scrollTop;
}
