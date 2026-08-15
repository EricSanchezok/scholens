export function withoutConversationSearchParam(
  pathname: string,
  search: string,
) {
  const next = new URLSearchParams(search);
  next.delete("conversation");
  const query = next.toString();
  return query ? `${pathname}?${query}` : pathname;
}
