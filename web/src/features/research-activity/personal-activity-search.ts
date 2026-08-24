import { z } from "zod";

import type { ResearchActivityRange } from "./types";

const personalActivityRangeSchema = z.enum(["30d", "90d", "365d", "all"]);
export type PersonalActivityRange = Exclude<ResearchActivityRange, "7d">;

export function parsePersonalActivityRange(
  params: URLSearchParams,
): PersonalActivityRange {
  return personalActivityRangeSchema.catch("365d").parse(params.get("range"));
}

export function serializePersonalActivityRange(range: PersonalActivityRange) {
  const params = new URLSearchParams();
  if (range !== "365d") params.set("range", range);
  return params;
}
