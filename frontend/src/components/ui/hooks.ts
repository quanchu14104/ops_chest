import { useCallback, useEffect, useState } from "react";

// Theo dõi một media query (vd bề rộng màn hình) và cập nhật khi đổi kích thước cửa sổ
export function useMediaQuery(query: string): boolean {
  const read = () => typeof window !== "undefined" && window.matchMedia(query).matches;
  const [match, setMatch] = useState(read);
  useEffect(() => {
    const mq = window.matchMedia(query);
    const on = () => setMatch(mq.matches);
    on();
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, [query]);
  return match;
}

// Lựa chọn nhỏ của người dùng (vd thu gọn thanh bên). localStorage có thể bị chặn: khi đó chỉ nhớ trong phiên.
export function useStoredState<T extends string>(key: string): [T | null, (v: T | null) => void] {
  const [value, setValue] = useState<T | null>(() => {
    try {
      return (localStorage.getItem(key) as T | null) ?? null;
    } catch {
      return null;
    }
  });
  const set = useCallback(
    (v: T | null) => {
      setValue(v);
      try {
        if (v == null) localStorage.removeItem(key);
        else localStorage.setItem(key, v);
      } catch {
        /* bỏ qua */
      }
    },
    [key],
  );
  return [value, set];
}
