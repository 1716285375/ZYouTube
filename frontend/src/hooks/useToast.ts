import { useCallback, useEffect, useRef, useState } from "react";

export type ToastType = "success" | "error" | "info";

export interface Toast {
  id: string;
  type: ToastType;
  message: string;
}

const createToastId = (label: string) => {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `${label}-${Date.now()}-${Math.random()}`;
};

export function useToast(autoDismissMs = 5000) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const timers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});

  const removeToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((toast) => toast.id !== id));
    const timer = timers.current[id];
    if (timer) {
      clearTimeout(timer);
      delete timers.current[id];
    }
  }, []);

  const pushToast = useCallback(
    (type: ToastType, message: string) => {
      const id = createToastId(type);
      setToasts((prev) => [...prev, { id, type, message }]);
      timers.current[id] = setTimeout(() => removeToast(id), autoDismissMs);
    },
    [autoDismissMs, removeToast],
  );

  useEffect(() => {
    return () => {
      Object.values(timers.current).forEach(clearTimeout);
      timers.current = {};
    };
  }, []);

  return { toasts, pushToast, removeToast };
}


