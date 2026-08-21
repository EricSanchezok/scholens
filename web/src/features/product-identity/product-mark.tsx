import { cn } from "@/lib/utilities/cn";

type ProductMarkSize = "compact" | "standard" | "display";

const markSizes: Record<ProductMarkSize, number> = {
  compact: 24,
  standard: 32,
  display: 80,
};

export function ProductMark({
  className,
  size = "compact",
}: {
  className?: string;
  size?: ProductMarkSize;
}) {
  const pixels = markSizes[size];
  const portrait =
    size === "display"
      ? "/brand/scholens-raven-portrait-128.png"
      : "/brand/scholens-raven-portrait-64.png";

  return (
    <span
      aria-hidden="true"
      className={cn(
        "inline-block shrink-0 rounded-full bg-cover bg-center",
        className,
      )}
      data-product-mark="portrait"
      style={{
        backgroundImage: `url('${portrait}')`,
        height: pixels,
        width: pixels,
      }}
    />
  );
}

export function ProductLockup({
  className,
  size = "compact",
}: {
  className?: string;
  size?: Exclude<ProductMarkSize, "display">;
}) {
  return (
    <span className={cn("inline-flex items-center gap-2", className)}>
      <ProductMark size={size} />
      <span>Scholens</span>
    </span>
  );
}
