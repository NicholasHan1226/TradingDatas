import { useCallback, useState } from 'react'

export function readStoredValue<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key)
    return raw === null ? fallback : (JSON.parse(raw) as T)
  } catch {
    return fallback
  }
}

export function writeStoredValue<T>(key: string, value: T): void {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    // Storage is an enhancement. The current page remains fully usable without it.
  }
}

export function usePersistentState<T>(key: string, fallback: T) {
  const [value, setValue] = useState<T>(() => readStoredValue(key, fallback))
  const update = useCallback(
    (next: T | ((current: T) => T)) => {
      setValue((current) => {
        const resolved = typeof next === 'function'
          ? (next as (current: T) => T)(current)
          : next
        writeStoredValue(key, resolved)
        return resolved
      })
    },
    [key],
  )
  return [value, update] as const
}
