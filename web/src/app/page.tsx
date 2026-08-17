import { HomePage } from "@/features/home";

type HomeSearchParams = Promise<Record<string, string | string[] | undefined>>;

function firstValue(value: string | string[] | undefined) {
  return Array.isArray(value) ? value[0] : value;
}

export default async function HomeRoute({
  searchParams,
}: {
  searchParams: HomeSearchParams;
}) {
  const query = await searchParams;
  const candidate = firstValue(query.conversation);
  const conversationId =
    candidate &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
      candidate,
    )
      ? candidate
      : undefined;
  const returnToQuery = new URLSearchParams();
  Object.entries(query).forEach(([key, value]) => {
    if (Array.isArray(value)) {
      value.forEach((item) => returnToQuery.append(key, item));
    } else if (value !== undefined) {
      returnToQuery.set(key, value);
    }
  });
  const serializedReturnTo = returnToQuery.toString();
  const anonymousReturnTo = serializedReturnTo
    ? `/?${serializedReturnTo}`
    : "/";

  return (
    <HomePage
      anonymousReturnTo={anonymousReturnTo}
      conversationId={conversationId}
    />
  );
}
