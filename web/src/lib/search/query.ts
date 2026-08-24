export const MINIMUM_SEARCH_QUERY_LENGTH = 2;

export function normalizeSearchQuery(query: string) {
  return query.trim();
}

export function isSearchQuery(query: string) {
  return (
    Array.from(normalizeSearchQuery(query)).length >=
    MINIMUM_SEARCH_QUERY_LENGTH
  );
}
