import * as React from 'react';

/** State mirrored to localStorage. Storage can be unavailable or full; the app then keeps it in memory. */
export function useStored<T>(key: string, initial: T) {
  const [value, setValue] = React.useState<T>(() => {
    try {
      const raw = window.localStorage.getItem(key);
      return raw === null ? initial : (JSON.parse(raw) as T);
    } catch {
      return initial;
    }
  });
  React.useEffect(() => {
    try {
      window.localStorage.setItem(key, JSON.stringify(value));
    } catch {
      // Ignore quota or privacy-mode errors.
    }
  }, [key, value]);
  return [value, setValue] as const;
}
