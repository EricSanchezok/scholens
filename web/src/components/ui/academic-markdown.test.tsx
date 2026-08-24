import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  AcademicMarkdown,
  normalizeAcademicMathDelimiters,
} from "./academic-markdown";

describe("academic math markdown", () => {
  it("normalizes balanced TeX delimiters and preserves incomplete streaming text", () => {
    const normalized = normalizeAcademicMathDelimiters(
      String.raw`Inline \(x^2\).

\[
\sum_{i=1}^{n} i
\]

Still streaming \(y +`,
    );

    expect(normalized).toContain("Inline $x^2$.");
    expect(normalized).toContain("$$\n\\sum_{i=1}^{n} i\n$$");
    expect(normalized).toContain(String.raw`Still streaming \(y +`);
  });

  it("does not reinterpret inline or fenced code as mathematics", () => {
    const markdown = [
      String.raw`Keep \(x\) in ` + "`" + String.raw`inline code \(y\)` + "`.",
      "",
      "```tex",
      String.raw`\[z\]`,
      "```",
      "",
    ].join("\n");

    expect(normalizeAcademicMathDelimiters(markdown)).toBe(
      [
        String.raw`Keep $x$ in ` + "`" + String.raw`inline code \(y\)` + "`.",
        "",
        "```tex",
        String.raw`\[z\]`,
        "```",
        "",
      ].join("\n"),
    );
  });

  it("renders dollar and backslash syntax with accessible MathML", () => {
    const { container } = render(
      <AcademicMarkdown>
        {String.raw`Inline $x^2$ and \(y^2\).

$$
\sum_{i=1}^{n} i
$$

\[\frac{a}{b}\]`}
      </AcademicMarkdown>,
    );

    expect(container.querySelectorAll(".katex")).toHaveLength(4);
    expect(container.querySelectorAll(".katex-mathml math")).toHaveLength(4);
    expect(
      container.querySelectorAll(".katex-html[aria-hidden='true']"),
    ).toHaveLength(4);
    expect(
      container.querySelectorAll(".katex-display.focus-recipe-scroll"),
    ).toHaveLength(2);
    expect(
      container.querySelectorAll(".katex-display[tabindex='0']"),
    ).toHaveLength(0);
  });
});
