/**
 * Kemory dashboard — Extension key hooks (chats-v1 UI).
 *
 * Backs the Devices page. Mint returns the plaintext key exactly once;
 * the consumer is responsible for keeping that value in component state
 * just long enough to show it in a copy-to-clipboard modal — we never
 * cache it in React Query.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  listExtensionKeys,
  mintExtensionKey,
  revokeExtensionKey,
  type ExtensionKeyMintRequest,
  type ExtensionKeyMintResponse,
} from '@/api/extensionKeys'

export function useExtensionKeys() {
  return useQuery({
    queryKey: ['extension-keys'],
    queryFn: listExtensionKeys,
    staleTime: 30_000,
  })
}

export function useMintExtensionKey() {
  const qc = useQueryClient()
  return useMutation<ExtensionKeyMintResponse, Error, ExtensionKeyMintRequest>({
    mutationFn: (data: ExtensionKeyMintRequest) => mintExtensionKey(data),
    onSuccess: () => {
      // Refetch the list so the new install row appears (without plaintext).
      qc.invalidateQueries({ queryKey: ['extension-keys'] })
    },
  })
}

export function useRevokeExtensionKey() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (keyId: string) => revokeExtensionKey(keyId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['extension-keys'] })
    },
  })
}
