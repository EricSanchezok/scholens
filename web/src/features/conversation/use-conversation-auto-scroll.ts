"use client";

import * as React from "react";

import {
  type ResolvedMotion,
  useMotionPreference,
} from "@/design-system/motion/motion-provider";

const BOTTOM_PROXIMITY_PX = 120;
const MIN_SCROLL_DELTA_PX = 0.5;
const SCROLL_TIME_CONSTANT_MS = 52;

type ConversationScroller = HTMLElement;

export function conversationBottomGap(scroller: {
  clientHeight: number;
  scrollHeight: number;
  scrollTop: number;
}) {
  return Math.max(
    0,
    scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight,
  );
}

export function nextConversationScrollTop({
  current,
  elapsedMs,
  target,
}: {
  current: number;
  elapsedMs: number;
  target: number;
}) {
  const distance = target - current;
  if (Math.abs(distance) <= MIN_SCROLL_DELTA_PX) return target;
  const boundedElapsed = Math.min(Math.max(elapsedMs, 0), 32);
  const progress = 1 - Math.exp(-boundedElapsed / SCROLL_TIME_CONSTANT_MS);
  const next = current + distance * progress;
  if (Math.abs(target - next) <= MIN_SCROLL_DELTA_PX) return target;
  return next;
}

export function conversationScrollTopForMotion({
  current,
  elapsedMs,
  resolvedMotion,
  target,
}: {
  current: number;
  elapsedMs: number;
  resolvedMotion: ResolvedMotion;
  target: number;
}) {
  return resolvedMotion === "reduced"
    ? target
    : nextConversationScrollTop({ current, elapsedMs, target });
}

export function nextConversationFollowingState({
  current,
  gap,
  movingUp,
  programmatic,
}: {
  current: boolean;
  gap: number;
  movingUp: boolean;
  programmatic: boolean;
}) {
  if (programmatic) return current;
  return gap < 2 || (!movingUp && gap < BOTTOM_PROXIMITY_PX);
}

export function useConversationAutoScroll({
  getScroller,
}: {
  getScroller: () => ConversationScroller | null;
}) {
  const { resolved: resolvedMotion } = useMotionPreference();
  const contentRef = React.useRef<HTMLDivElement>(null);
  const followingRef = React.useRef(true);
  const frameRef = React.useRef<number | undefined>(undefined);
  const previousFrameTimeRef = React.useRef<number | undefined>(undefined);
  const lastProgrammaticWriteRef = React.useRef(0);
  const lastProgrammaticTopRef = React.useRef<number | undefined>(undefined);
  const lastObservedTopRef = React.useRef(0);
  const touchYRef = React.useRef<number | undefined>(undefined);
  const animateToLatestRef = React.useRef<(frameTime: number) => void>(
    () => undefined,
  );
  const [showJumpToLatest, setShowJumpToLatest] = React.useState(false);

  const updateJumpVisibility = React.useCallback(
    (scroller: ConversationScroller) => {
      const overflowing = scroller.scrollHeight > scroller.clientHeight + 32;
      const awayFromBottom =
        conversationBottomGap(scroller) >= BOTTOM_PROXIMITY_PX;
      setShowJumpToLatest(
        overflowing && awayFromBottom && !followingRef.current,
      );
    },
    [],
  );

  const stopAnimation = React.useCallback(() => {
    if (frameRef.current !== undefined) {
      window.cancelAnimationFrame(frameRef.current);
      frameRef.current = undefined;
    }
    previousFrameTimeRef.current = undefined;
  }, []);

  const animateToLatest = React.useCallback(
    (frameTime: number) => {
      frameRef.current = undefined;
      const scroller = getScroller();
      if (!scroller || !followingRef.current) {
        previousFrameTimeRef.current = undefined;
        return;
      }

      const target = Math.max(0, scroller.scrollHeight - scroller.clientHeight);
      const elapsedMs =
        previousFrameTimeRef.current === undefined
          ? 16
          : frameTime - previousFrameTimeRef.current;
      const next = conversationScrollTopForMotion({
        current: scroller.scrollTop,
        elapsedMs,
        resolvedMotion,
        target,
      });

      previousFrameTimeRef.current = frameTime;
      lastProgrammaticWriteRef.current = window.performance.now();
      lastProgrammaticTopRef.current = next;
      lastObservedTopRef.current = next;
      scroller.scrollTop = next;
      setShowJumpToLatest(false);

      if (next !== target) {
        frameRef.current = window.requestAnimationFrame((nextFrameTime) =>
          animateToLatestRef.current(nextFrameTime),
        );
      } else {
        previousFrameTimeRef.current = undefined;
      }
    },
    [getScroller, resolvedMotion],
  );

  React.useEffect(() => {
    animateToLatestRef.current = animateToLatest;
  }, [animateToLatest]);

  const requestFollowFrame = React.useCallback(() => {
    if (!followingRef.current || frameRef.current !== undefined) return;
    frameRef.current = window.requestAnimationFrame(animateToLatest);
  }, [animateToLatest]);

  const pauseFollowing = React.useCallback(() => {
    const scroller = getScroller();
    followingRef.current = false;
    stopAnimation();
    if (scroller) updateJumpVisibility(scroller);
  }, [getScroller, stopAnimation, updateJumpVisibility]);

  const jumpToLatest = React.useCallback(() => {
    stopAnimation();
    followingRef.current = true;
    setShowJumpToLatest(false);
    animateToLatestRef.current(window.performance.now());
  }, [stopAnimation]);

  React.useEffect(() => {
    const scroller = getScroller();
    const content = contentRef.current;
    if (!scroller || !content) return;

    function handleScroll() {
      const gap = conversationBottomGap(scroller!);
      const scrollTop = scroller!.scrollTop;
      const movingUp = scrollTop < lastObservedTopRef.current - 0.5;
      const programmatic =
        window.performance.now() - lastProgrammaticWriteRef.current < 80 &&
        lastProgrammaticTopRef.current !== undefined &&
        Math.abs(scrollTop - lastProgrammaticTopRef.current) < 1;
      const following = nextConversationFollowingState({
        current: followingRef.current,
        gap,
        movingUp,
        programmatic,
      });
      followingRef.current = following;
      if (!following) {
        stopAnimation();
      }
      lastObservedTopRef.current = scrollTop;
      updateJumpVisibility(scroller!);
    }

    function handleWheel(event: WheelEvent) {
      if (event.deltaY < 0) pauseFollowing();
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (
        event.key === "ArrowUp" ||
        event.key === "PageUp" ||
        event.key === "Home"
      ) {
        pauseFollowing();
      }
    }

    function handleTouchStart(event: TouchEvent) {
      touchYRef.current = event.touches[0]?.clientY;
    }

    function handleTouchMove(event: TouchEvent) {
      const previousY = touchYRef.current;
      const nextY = event.touches[0]?.clientY;
      if (previousY !== undefined && nextY !== undefined && nextY > previousY) {
        pauseFollowing();
      }
      touchYRef.current = nextY;
    }

    const resizeObserver = new ResizeObserver(() => {
      if (followingRef.current) requestFollowFrame();
      else updateJumpVisibility(scroller);
    });
    lastObservedTopRef.current = scroller.scrollTop;
    resizeObserver.observe(content);
    resizeObserver.observe(scroller);
    scroller.addEventListener("scroll", handleScroll, { passive: true });
    scroller.addEventListener("wheel", handleWheel, { passive: true });
    scroller.addEventListener("keydown", handleKeyDown);
    scroller.addEventListener("touchstart", handleTouchStart, {
      passive: true,
    });
    scroller.addEventListener("touchmove", handleTouchMove, { passive: true });

    requestFollowFrame();
    return () => {
      resizeObserver.disconnect();
      scroller.removeEventListener("scroll", handleScroll);
      scroller.removeEventListener("wheel", handleWheel);
      scroller.removeEventListener("keydown", handleKeyDown);
      scroller.removeEventListener("touchstart", handleTouchStart);
      scroller.removeEventListener("touchmove", handleTouchMove);
      stopAnimation();
    };
  }, [
    getScroller,
    pauseFollowing,
    requestFollowFrame,
    stopAnimation,
    updateJumpVisibility,
  ]);

  return {
    contentRef,
    jumpToLatest,
    pauseFollowing,
    showJumpToLatest,
  };
}
