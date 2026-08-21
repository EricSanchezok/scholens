"use client";

import Image from "next/image";
import * as React from "react";

import { cn } from "@/lib/utilities/cn";

export type AvatarSource = {
  expires_at: string;
  url: string;
  version: string;
};

export type AvatarProps = Omit<
  React.HTMLAttributes<HTMLSpanElement>,
  "children"
> & {
  fallback: string;
  onImageError?: (source: AvatarSource) => void;
  sizes?: string;
  source?: AvatarSource | null;
};

export function Avatar({
  className,
  fallback,
  onImageError,
  sizes = "64px",
  source,
  ...props
}: AvatarProps) {
  const [failedUrl, setFailedUrl] = React.useState<string>();
  const showImage = Boolean(source && failedUrl !== source.url);

  return (
    <span
      aria-hidden="true"
      className={cn(
        "bg-pressed text-secondary relative grid shrink-0 place-items-center overflow-hidden rounded-full font-medium",
        className,
      )}
      data-avatar-state={showImage ? "image" : "fallback"}
      {...props}
    >
      {source && showImage ? (
        <Image
          alt=""
          className="object-cover"
          fill
          onError={() => {
            setFailedUrl(source.url);
            onImageError?.(source);
          }}
          referrerPolicy="no-referrer"
          sizes={sizes}
          src={source.url}
          unoptimized
        />
      ) : (
        fallback
      )}
    </span>
  );
}
