import { useInfiniteQuery } from '@tanstack/react-query'

import {
  listNamespaceTimeline,
  type TimelineKind,
  type TimelineResponse,
} from '@/api/namespaceTimeline'

export function useNamespaceTimeline(
  namespace: string | null | undefined,
  options: { types?: TimelineKind[]; limit?: number } = {},
) {
  const typesKey = (options.types ?? []).join(',')
  return useInfiniteQuery<TimelineResponse>({
    queryKey: ['namespace-timeline', namespace ?? '', typesKey, options.limit ?? 40],
    queryFn: ({ pageParam }) =>
      listNamespaceTimeline({
        namespace: namespace!,
        types: options.types,
        cursor: pageParam as string | undefined,
        limit: options.limit,
      }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => (last.has_more ? (last.next_cursor ?? undefined) : undefined),
    enabled: !!namespace,
    staleTime: 15_000,
  })
}
