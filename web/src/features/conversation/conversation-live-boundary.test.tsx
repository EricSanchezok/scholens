import { act, render } from "@testing-library/react";
import * as React from "react";
import { describe, expect, it } from "vitest";

import { ConversationLiveStore } from "./conversation-live-store";
import { createLiveTurn } from "./conversation-state";

const responseId = "60000000-0000-4000-8000-000000000001";

describe("conversation live render boundaries", () => {
  it("rerenders content without rerendering the transcript parent or worklog", () => {
    const store = new ConversationLiveStore(
      createLiveTurn("turn-1", responseId, "Question"),
    );
    store.dispatch({
      type: "assistant_candidate_start",
      response_id: responseId,
      item_id: "answer-1",
      sequence: 1,
    });
    store.dispatch({
      type: "assistant_candidate_delta",
      response_id: responseId,
      item_id: "answer-1",
      delta: "first",
    });
    store.flush();

    let transcriptRenders = 0;
    let contentRenders = 0;
    let worklogRenders = 0;

    function ContentLeaf() {
      React.useSyncExternalStore(
        store.subscribeContent,
        store.getContentSnapshot,
        store.getContentSnapshot,
      );
      contentRenders += 1;
      return null;
    }

    function WorklogLeaf() {
      React.useSyncExternalStore(
        store.subscribeWorklog,
        store.getWorklogSnapshot,
        store.getWorklogSnapshot,
      );
      worklogRenders += 1;
      return null;
    }

    function Transcript() {
      React.useSyncExternalStore(
        store.subscribeMetadata,
        store.getMetadataSnapshot,
        store.getMetadataSnapshot,
      );
      transcriptRenders += 1;
      return (
        <>
          <ContentLeaf />
          <WorklogLeaf />
        </>
      );
    }

    render(<Transcript />);
    const initialTranscriptRenders = transcriptRenders;
    const initialContentRenders = contentRenders;
    const initialWorklogRenders = worklogRenders;

    act(() => {
      store.dispatch({
        type: "assistant_candidate_delta",
        response_id: responseId,
        item_id: "answer-1",
        delta: " second",
      });
      store.flush();
    });

    expect(contentRenders).toBe(initialContentRenders + 1);
    expect(transcriptRenders).toBe(initialTranscriptRenders);
    expect(worklogRenders).toBe(initialWorklogRenders);
  });
});
