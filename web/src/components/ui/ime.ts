type KeyboardEventWithComposition = {
  nativeEvent: Pick<KeyboardEvent, "isComposing" | "keyCode">;
};

const IME_PROCESS_KEY_CODE = 229;

/**
 * Returns true while an IME is using the current key event to compose text.
 *
 * `isComposing` is the standards-based signal. The legacy 229 check remains a
 * narrow compatibility fallback for Safari, which can dispatch the Enter key
 * that confirms a candidate after `compositionend` with `isComposing=false`.
 */
export function isImeComposing(event: KeyboardEventWithComposition) {
  return (
    event.nativeEvent.isComposing ||
    event.nativeEvent.keyCode === IME_PROCESS_KEY_CODE
  );
}
