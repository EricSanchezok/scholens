"use client";

import * as AlertDialogPrimitive from "@radix-ui/react-alert-dialog";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { Xmark } from "iconoir-react";
import * as React from "react";

import { Icon } from "@/design-system/icons/icon";
import { cn } from "@/lib/utilities/cn";
import { IconButton } from "./button";

const overlayClass =
  "motion-overlay fixed inset-0 z-[80] bg-[var(--color-overlay-backdrop)] backdrop-blur-sm";
const contentClass =
  "motion-dialog border-line bg-elevated shadow-modal fixed top-1/2 left-1/2 z-[80] flex max-h-[min(88dvh,46rem)] w-[min(92vw,36rem)] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-[var(--radius-xl)] border p-0 outline-none";
const responsiveBottomContentClass =
  "motion-responsive-bottom border-line bg-elevated shadow-modal fixed inset-x-0 bottom-0 z-[80] flex max-h-[calc(100dvh-max(env(safe-area-inset-top),1rem))] w-full flex-col overflow-hidden rounded-t-[var(--radius-xl)] border border-b-0 p-0 outline-none lg:top-1/2 lg:left-1/2 lg:bottom-auto lg:max-h-[min(82dvh,46rem)] lg:w-[min(92vw,36rem)] lg:-translate-x-1/2 lg:-translate-y-1/2 lg:rounded-[var(--radius-xl)] lg:border";
const responsiveFullContentClass =
  "motion-responsive-full border-line bg-elevated shadow-modal fixed inset-0 z-[80] flex h-dvh w-full flex-col overflow-hidden p-0 outline-none lg:inset-auto lg:top-1/2 lg:left-1/2 lg:h-[min(90dvh,47.5rem)] lg:w-[min(94vw,70rem)] lg:-translate-x-1/2 lg:-translate-y-1/2 lg:rounded-[var(--radius-xl)] lg:border";

export const Dialog = DialogPrimitive.Root;
export const DialogTrigger = DialogPrimitive.Trigger;
export const DialogClose = DialogPrimitive.Close;
export const DialogHandle = ({ className }: { className?: string }) => (
  <div
    aria-hidden="true"
    className={cn(
      "mx-auto mt-2 h-1 w-10 shrink-0 rounded-full bg-[var(--color-border-strong)] lg:hidden",
      className,
    )}
    data-slot="dialog-handle"
  />
);
export const DialogHeader = ({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) => (
  <div
    className={cn(
      "border-line shrink-0 border-b px-5 pt-5 pr-14 pb-4 lg:px-6",
      className,
    )}
    data-slot="dialog-header"
    {...props}
  />
);
export const DialogBody = ({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) => (
  <div
    className={cn(
      "min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 py-5 lg:px-6",
      className,
    )}
    data-slot="dialog-body"
    {...props}
  />
);
export const DialogFooter = ({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) => (
  <div
    className={cn(
      "border-line flex shrink-0 flex-wrap items-center justify-end gap-2 border-t px-5 pt-4 pb-[max(1rem,env(safe-area-inset-bottom))] lg:px-6 lg:pb-4",
      className,
    )}
    data-slot="dialog-footer"
    {...props}
  />
);
export const DialogTitle = (
  props: React.ComponentPropsWithoutRef<typeof DialogPrimitive.Title>,
) => (
  <DialogPrimitive.Title
    className="text-lg leading-6 font-semibold"
    data-slot="dialog-title"
    {...props}
  />
);
export const DialogDescription = (
  props: React.ComponentPropsWithoutRef<typeof DialogPrimitive.Description>,
) => (
  <DialogPrimitive.Description
    className="text-muted mt-2 text-sm"
    data-slot="dialog-description"
    {...props}
  />
);
export const DialogContent = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content> & {
    closeLabel: string;
    placement?: "center" | "responsive-bottom" | "responsive-full";
  }
>(
  (
    { children, className, closeLabel, placement = "center", ...props },
    ref,
  ) => (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay
        className={overlayClass}
        data-slot="dialog-overlay"
      />
      <DialogPrimitive.Content
        className={cn(
          placement === "responsive-bottom"
            ? responsiveBottomContentClass
            : placement === "responsive-full"
              ? responsiveFullContentClass
              : contentClass,
          className,
        )}
        data-slot="dialog-content"
        ref={ref}
        {...props}
      >
        {children}
        <DialogPrimitive.Close asChild>
          <IconButton
            className="absolute top-3 right-3 z-10"
            label={closeLabel}
            variant="ghost"
          >
            <Icon glyph={Xmark} size={20} />
          </IconButton>
        </DialogPrimitive.Close>
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  ),
);
DialogContent.displayName = DialogPrimitive.Content.displayName;

export const AlertDialog = AlertDialogPrimitive.Root;
export const AlertDialogTrigger = AlertDialogPrimitive.Trigger;
export const AlertDialogCancel = AlertDialogPrimitive.Cancel;
export const AlertDialogAction = AlertDialogPrimitive.Action;
export const AlertDialogTitle = (
  props: React.ComponentPropsWithoutRef<typeof AlertDialogPrimitive.Title>,
) => (
  <AlertDialogPrimitive.Title className="text-xl font-semibold" {...props} />
);
export const AlertDialogDescription = (
  props: React.ComponentPropsWithoutRef<
    typeof AlertDialogPrimitive.Description
  >,
) => (
  <AlertDialogPrimitive.Description
    className="text-muted mt-2 text-sm"
    {...props}
  />
);
export const AlertDialogContent = React.forwardRef<
  React.ElementRef<typeof AlertDialogPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof AlertDialogPrimitive.Content>
>(({ className, ...props }, ref) => (
  <AlertDialogPrimitive.Portal>
    <AlertDialogPrimitive.Overlay className={overlayClass} />
    <AlertDialogPrimitive.Content
      className={cn(contentClass, "p-6", className)}
      ref={ref}
      {...props}
    />
  </AlertDialogPrimitive.Portal>
));
AlertDialogContent.displayName = AlertDialogPrimitive.Content.displayName;
