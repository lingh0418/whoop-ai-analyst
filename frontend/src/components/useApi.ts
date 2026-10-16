import { useCallback, useEffect, useState } from 'react'
import { api } from '../api'

export function useApi<T = any>(path: string | null, deps: unknown[] = []) {  // eslint-disable-line @typescript-eslint/no-explicit-any
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(!!path)

  const load = useCallback(async () => {
    if (!path) return
    setLoading(true)
    setError(null)
    try {
      setData(await api.get<T>(path))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, ...deps])

  useEffect(() => {
    load()
  }, [load])

  return { data, error, loading, reload: load, setData }
}
