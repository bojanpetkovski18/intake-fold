import {
  QueryCache,
  QueryClient,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  ApiError,
  getDocument,
  getSession,
  listDeadJobs,
  listDocuments,
  retryJob,
  signIn,
  signOut,
} from "./client";
import type { DocumentStatus } from "./types";

const SESSION_KEY = ["session"];
const ACTIVE_POLL_MS = 2000;
const ACTIVE_STATUSES: DocumentStatus[] = ["queued", "processing"];

export function createQueryClient() {
  const client: QueryClient = new QueryClient({
    queryCache: new QueryCache({
      onError: (error) => {
        // An expired session surfaces on whichever request notices first.
        if (error instanceof ApiError && error.status === 401) {
          client.setQueryData(SESSION_KEY, null);
        }
      },
    }),
    defaultOptions: {
      queries: {
        retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2,
        refetchOnWindowFocus: false,
      },
    },
  });
  return client;
}

export function useSession() {
  return useQuery({ queryKey: SESSION_KEY, queryFn: getSession });
}

export function useSignIn() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ email, password }: { email: string; password: string }) =>
      signIn(email, password),
    onSuccess: (session) => {
      client.setQueryData(SESSION_KEY, session);
    },
  });
}

export function useSignOut() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: signOut,
    onSuccess: () => {
      client.setQueryData(SESSION_KEY, null);
      // Nothing from one person's session may remain for the next. Not client.clear(), which
      // would also drop this mutation before its caller's onSuccess runs.
      client.removeQueries({ predicate: (query) => query.queryKey[0] !== SESSION_KEY[0] });
    },
  });
}

export function useDocuments(status: DocumentStatus | null) {
  return useInfiniteQuery({
    queryKey: ["documents", status],
    queryFn: ({ pageParam }) => listDocuments({ status, cursor: pageParam }),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.nextCursor,
    refetchInterval: (query) => {
      const items = query.state.data?.pages.flatMap((page) => page.items) ?? [];
      return items.some((item) => ACTIVE_STATUSES.includes(item.status)) ? ACTIVE_POLL_MS : false;
    },
  });
}

export function useDocument(id: string) {
  return useQuery({ queryKey: ["document", id], queryFn: () => getDocument(id) });
}

export function useDeadJobs() {
  return useInfiniteQuery({
    queryKey: ["dead-jobs"],
    queryFn: ({ pageParam }) => listDeadJobs(pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.nextCursor,
  });
}

export function useRetryJob() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: retryJob,
    onSuccess: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: ["dead-jobs"] }),
        client.invalidateQueries({ queryKey: ["documents"] }),
      ]);
    },
  });
}
