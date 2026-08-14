import { describe, expect, it } from "vitest";

import { semanticIcons } from "./semantic-icons";

describe("semantic icon registry", () => {
  it("assigns one Iconoir glyph to one product semantic", () => {
    const glyphs = Object.values(semanticIcons);

    expect(new Set(glyphs).size).toBe(glyphs.length);
  });

  it("pins the shared creation and annotation semantics", () => {
    expect(semanticIcons).toMatchObject({
      AddAnnotationIcon: "Notes",
      AddIcon: "Plus",
      AskIcon: "ChatBubbleQuestion",
      EditIcon: "EditPencil",
      NewConversationIcon: "PageEdit",
    });
  });
});
