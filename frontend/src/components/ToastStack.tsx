import type { Toast } from "../hooks/useToast";

type ToastStackProps = {
  toasts: Toast[];
  onDismiss: (id: string) => void;
};

const iconMap = {
  success: "✅",
  error: "⚠️",
  info: "💡",
} as const;

export function ToastStack({ toasts, onDismiss }: ToastStackProps) {
  if (toasts.length === 0) return null;
  return (
    <div className="toast-stack">
      {toasts.map((toast) => (
        <div key={toast.id} className={`toast ${toast.type}`}>
          <span className="toast-icon">{iconMap[toast.type]}</span>
          <span className="toast-message">{toast.message}</span>
          <button type="button" onClick={() => onDismiss(toast.id)}>
            ×
          </button>
        </div>
      ))}
    </div>
  );
}

export default ToastStack;


