export type ReaderScrollContainerGeometry = {
  clientHeight: number;
  scrollHeight: number;
  scrollTop: number;
  top: number;
};

export type ReaderScrollTargetGeometry = { height: number; top: number };

export function readerScrollTopForTarget({
  alignment,
  container,
  startOffset = 0,
  target,
}: {
  container: ReaderScrollContainerGeometry;
  target: ReaderScrollTargetGeometry;
  alignment: "start" | "center";
  startOffset?: number;
}) {
  const targetTop = target.top - container.top + container.scrollTop;
  const desired =
    alignment === "start"
      ? targetTop - startOffset
      : targetTop + target.height / 2 - container.clientHeight / 2;
  return Math.min(
    Math.max(desired, 0),
    Math.max(container.scrollHeight - container.clientHeight, 0),
  );
}
