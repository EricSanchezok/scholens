import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, fireEvent, userEvent, waitFor, within } from "storybook/test";
import { useState } from "react";

import { Button, LinkButton } from "./button";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "./dialog";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "./dropdown-menu";
import { ScrollArea, VisuallyHidden } from "./scroll-area";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetTitle,
  SheetTrigger,
} from "./sheet";
import { Pagination } from "./tabs-pagination";
import { ToastProvider, useToast } from "./toast";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "./tooltip-popover";

const meta = {
  title: "Examples/Overlays and navigation",
  tags: ["autodocs"],
  parameters: { layout: "padded" },
} satisfies Meta;
export default meta;
type Story = StoryObj<typeof meta>;

export const MenusAndDisclosure: Story = {
  render: () => (
    <TooltipProvider>
      <div className="flex flex-wrap gap-3">
        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="secondary">Tooltip</Button>
          </TooltipTrigger>
          <TooltipContent>Keyboard-accessible help</TooltipContent>
        </Tooltip>
        <Popover>
          <PopoverTrigger asChild>
            <Button variant="secondary">Popover</Button>
          </PopoverTrigger>
          <PopoverContent>
            <p className="text-sm font-medium">Contextual controls</p>
            <p className="text-muted mt-1 text-sm">
              This surface inherits the active appearance.
            </p>
          </PopoverContent>
        </Popover>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="secondary">Open menu</Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent>
            <DropdownMenuLabel>Actions</DropdownMenuLabel>
            <DropdownMenuItem>Rename</DropdownMenuItem>
            <DropdownMenuCheckboxItem checked>
              Keep visible
            </DropdownMenuCheckboxItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem destructive>Archive</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </TooltipProvider>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Open menu" }));
    await expect(within(document.body).getByText("Rename")).toBeVisible();
    await userEvent.keyboard("{Escape}");
  },
};

export const ModalAndPanel: Story = {
  render: () => (
    <div className="flex gap-3">
      <AlertDialog>
        <AlertDialogTrigger asChild>
          <Button variant="danger">Open confirmation</Button>
        </AlertDialogTrigger>
        <AlertDialogContent>
          <AlertDialogTitle>Archive this item?</AlertDialogTitle>
          <AlertDialogDescription>
            It remains recoverable from the archive.
          </AlertDialogDescription>
          <div className="mt-6 flex justify-end gap-2">
            <AlertDialogCancel asChild>
              <Button variant="secondary">Cancel</Button>
            </AlertDialogCancel>
            <AlertDialogAction asChild>
              <Button variant="danger">Archive</Button>
            </AlertDialogAction>
          </div>
        </AlertDialogContent>
      </AlertDialog>
      <Sheet>
        <SheetTrigger asChild>
          <Button variant="secondary">Open panel</Button>
        </SheetTrigger>
        <SheetContent closeLabel="Close panel">
          <SheetTitle className="text-xl font-semibold">Side panel</SheetTitle>
          <SheetDescription className="text-muted mt-2 text-sm">
            Narrow layouts remain independently scrollable.
          </SheetDescription>
        </SheetContent>
      </Sheet>
    </div>
  ),
};

function StatefulNavigation() {
  const [page, setPage] = useState(2);
  return (
    <ToastProvider dismissLabel="Dismiss notification">
      <StatefulNavigationContent page={page} setPage={setPage} />
    </ToastProvider>
  );
}

function StatefulNavigationContent({
  page,
  setPage,
}: {
  page: number;
  setPage: (page: number) => void;
}) {
  const { notify } = useToast();
  return (
    <div className="grid justify-items-start gap-5">
      <Pagination onPageChange={setPage} page={page} pages={8} />
      <p aria-live="polite" className="text-muted text-sm">
        Page {page} of 8
      </p>
      <div className="flex gap-3">
        <Button
          onClick={() =>
            notify({
              description: "The isolated action completed.",
              title: "Saved",
            })
          }
          variant="secondary"
        >
          Show toast
        </Button>
        <LinkButton href="#isolated-link" variant="ghost">
          Link action
        </LinkButton>
      </div>
    </div>
  );
}

export const PaginationAndToast: Story = {
  render: () => <StatefulNavigation />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Next page" }));
    await expect(canvas.getByText("Page 3 of 8")).toBeVisible();
    await userEvent.click(canvas.getByRole("button", { name: "Show toast" }));
    await expect(within(document.body).getByText("Saved")).toBeVisible();
  },
};

export const ScrollAndHiddenContent: Story = {
  render: () => (
    <ScrollArea className="border-line h-40 max-w-sm rounded-[var(--radius-lg)] border p-4">
      <VisuallyHidden>Scrollable sample</VisuallyHidden>
      <div className="grid gap-3">
        {Array.from({ length: 12 }, (_, index) => (
          <p className="text-sm" key={index}>
            Accessible scroll row {index + 1}
          </p>
        ))}
      </div>
    </ScrollArea>
  ),
  play: async ({ canvasElement }) => {
    const root = canvasElement.querySelector<HTMLElement>(
      "[data-scrollbar-root]",
    );
    const viewport = root?.querySelector<HTMLElement>(
      "[data-radix-scroll-area-viewport]",
    );
    expect(root).toBeInTheDocument();
    expect(viewport).toBeInTheDocument();

    viewport!.scrollTop = 96;
    fireEvent.scroll(viewport!);

    await expect(viewport!).toHaveAttribute("data-scrollbar-active");
    await waitFor(() =>
      expect(
        root!.querySelector(
          '[data-scrollbar-track][data-orientation="vertical"]',
        ),
      ).toBeInTheDocument(),
    );
    await waitFor(() =>
      expect(
        root!.querySelector(
          '[data-scrollbar-track][data-orientation="vertical"] [data-scrollbar-thumb]',
        ),
      ).toBeInTheDocument(),
    );
    const track = root!.querySelector<HTMLElement>(
      '[data-scrollbar-track][data-orientation="vertical"]',
    )!;
    const thumb = track.querySelector<HTMLElement>("[data-scrollbar-thumb]")!;
    await waitFor(() => expect(getComputedStyle(track).opacity).toBe("1"));
    expect(getComputedStyle(track).width).toBe("4px");
    expect(getComputedStyle(thumb).width).toBe("2px");
    await waitFor(
      () => expect(viewport!).not.toHaveAttribute("data-scrollbar-active"),
      { timeout: 1_200 },
    );
  },
};
