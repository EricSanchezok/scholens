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

  if (size === "display") {
    return (
      <span
        aria-hidden="true"
        className={cn(
          "inline-block shrink-0 rounded-full bg-cover bg-center",
          className,
        )}
        data-product-mark="portrait"
        style={{
          backgroundImage: "url('/brand/scholens-raven-portrait-128.png')",
          height: pixels,
          width: pixels,
        }}
      />
    );
  }

  return (
    <span
      aria-hidden="true"
      className={cn("inline-block shrink-0 bg-current", className)}
      data-product-mark="micro"
      style={{
        height: pixels,
        maskImage: "url('/brand/scholens-raven-micro.svg')",
        maskPosition: "center",
        maskRepeat: "no-repeat",
        maskSize: "contain",
        width: pixels,
        WebkitMaskImage: "url('/brand/scholens-raven-micro.svg')",
        WebkitMaskPosition: "center",
        WebkitMaskRepeat: "no-repeat",
        WebkitMaskSize: "contain",
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
