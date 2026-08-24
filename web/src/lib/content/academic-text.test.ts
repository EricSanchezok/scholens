import { describe, expect, it } from "vitest";

import {
  academicMarkdownToPlainText,
  sanitizeAcademicMarkdown,
} from "./academic-text";

describe("academic text normalization", () => {
  it("preserves supported academic notation without exposing raw HTML", () => {
    const value = sanitizeAcademicMarkdown(
      "Author<sup>1,2</sup><!-- hidden --><br>H<sub>2</sub>O <unknown>visible</unknown> �",
    );

    expect(value).toBe("Author$^{1,2}$  \nH$_{2}$O visible ");
    expect(value).not.toContain("<sup>");
    expect(value).not.toContain("hidden");
    expect(value).not.toContain("�");
  });

  it("removes executable HTML, controls, and Markdown presentation syntax", () => {
    const value = academicMarkdownToPlainText(
      "## **Method**\u0000<script>alert('hidden')</script>&lt;script&gt;encoded-hidden()&lt;/script&gt;<p>[Result](https://example.test) &amp; H<sub>2</sub>O</p>\n| --- | --- |\n| one | two |",
    );

    expect(value).toBe("Method Result & H2O one two");
    expect(value).not.toMatch(/[<>\u0000]/);
  });

  it("keeps meaningful image alternatives and fenced-code content", () => {
    expect(
      academicMarkdownToPlainText(
        "![architecture](figure.png)\n```ts\nconst answer = 42;\n```",
      ),
    ).toBe("architecture const answer = 42;");
  });

  it("rejects numeric entities that are not Unicode scalar values", () => {
    const entity = (value: string) => `&${"#"}${value};`;
    const value = academicMarkdownToPlainText(
      `before ${entity("55296")} ${entity("xDFFF")} ${entity("128187")} after`,
    );

    expect(value).toBe("before 💻 after");
    expect(
      Array.from(value).some((character) => {
        const codeUnit = character.charCodeAt(0);
        return (
          character.length === 1 && codeUnit >= 0xd800 && codeUnit <= 0xdfff
        );
      }),
    ).toBe(false);
  });
});
