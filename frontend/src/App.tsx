import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
type Locale = "zh" | "en";
import type { FormEvent } from "react";
import { ToastStack } from "./components/ToastStack";
import { useToast } from "./hooks/useToast";
import { DEFAULT_PROVIDER_ID, providerOptions } from "./data/providers";
import {
  ApiError,
  buildApiUrl,
  postJson,
  readError,
  requestJson,
  toPublicAssetUrl,
} from "./lib/api";
import {
  BookMarked,
  ListChecks,
  Moon,
  SendHorizontal,
  Settings2,
  Sparkles,
  Sun,
  UserRound,
  X,
} from "lucide-react";
import type {
  SubtitleAnalysisRequest,
  SubtitleAnalysisResponse,
  SubtitleDownloadRequest,
  SubtitleDownloadResponse,
  SubtitleFormat,
  SubtitleListResponse,
  SubtitlePlaylistDownloadResponse,
  SubtitlePlaylistProgressResponse,
  SubtitleTrack,
  VideoJobResponse,
  VideoQuality,
} from "./types/api";

const subtitleFormats: {
  value: SubtitleFormat;
  label: Record<Locale, string>;
}[] = [
  { value: "srt", label: { zh: "SRT · 字幕", en: "SRT · SubRip" } },
  { value: "vtt", label: { zh: "VTT · WebVTT", en: "VTT · WebVTT" } },
  { value: "ass", label: { zh: "ASS · 字幕", en: "ASS · Advanced SubStation" } },
  { value: "json3", label: { zh: "JSON3 · 结构化", en: "JSON3 · Structured captions" } },
  { value: "ttml", label: { zh: "TTML · Timed Text", en: "TTML · Timed Text" } },
];

const defaultTemplates: Record<Locale, string> = {
  zh: `你是一个 Notion 软件使用专家，将下述内容以 Notion 笔记格式输出，要求美观简洁。
标题和列表前使用图标，如 🎮、🏛、🛠️、🔗、⚡、📦、📚、📝、✅、⚙️、🏷、🏊、🪂、🤖、👤、❌、🎶、🎇、🎵。
标题之间用 --- 分隔。
若存在数学公式，请使用 Notion 支持的公式语法，确保复制后可直接渲染。
请将视频内容整理成笔记，保证准确性的同时尽量通俗易懂，并保留必要的原语术语。
视频主讲人：{speaker}
演讲主题：{topic}
演讲内容如下：
{subtitle_body}`,
  en: `You are a Notion power user. Reformat the following video transcript into a clean Notion-style note.
Use expressive icons (🎯, 🧠, 🧱, 🛠️, 🔗, ⚡, 📦, 📚, 📝, ✅, ⚙️, 🏷, 🧭, 🤖, 👥, ❌, 🎶) before titles and list bullets.
Separate major sections with --- lines. When math formulas appear, output them using Notion-compatible LaTeX so users can paste directly.
Aim for accurate yet approachable explanations, preserving original terminology if it adds clarity.
Speaker: {speaker}
Topic: {topic}
Transcript:
{subtitle_body}`,
};

const welcomeMessages: Record<Locale, string> = {
  zh: "你好！先在左侧完成字幕下载，再告诉我希望整理的格式或重点，我会结合字幕帮你生成高质量笔记。",
  en: "Hi! Start by grabbing subtitles on the left, then tell me what kind of summary you need. I’ll use the captions to craft a polished note.",
};

const defaultProviderOption =
  providerOptions.find((option) => option.value === DEFAULT_PROVIDER_ID) ??
  providerOptions[0];

const videoQualities: {
  value: VideoQuality;
  label: Record<Locale, string>;
}[] = [
  { value: "best", label: { zh: "自动（最高画质）", en: "Auto (Best available)" } },
  { value: "2160p", label: { zh: "2160p · 4K", en: "2160p · 4K" } },
  { value: "1440p", label: { zh: "1440p · 2K", en: "1440p · 2K" } },
  { value: "1080p", label: { zh: "1080p · FHD", en: "1080p · FHD" } },
  { value: "720p", label: { zh: "720p · HD", en: "720p · HD" } },
  { value: "480p", label: { zh: "480p", en: "480p" } },
  { value: "360p", label: { zh: "360p", en: "360p" } },
  { value: "240p", label: { zh: "240p", en: "240p" } },
  { value: "144p", label: { zh: "144p", en: "144p" } },
];

type StatusState =
  | { type: "idle" }
  | { type: "loading"; message: string }
  | { type: "success"; message: string }
  | { type: "error"; message: string };

type ChatMessage = {
  id: string;
  role: "assistant" | "user";
  content: string;
  timestamp: number;
};

const MESSAGE_SNIPPET_LIMIT = 280;

const markdownRemarkPlugins = [remarkGfm, remarkMath] as const;
const markdownRehypePlugins = [rehypeKatex] as const;

const createMessage = (
  role: ChatMessage["role"],
  content: string,
  id?: string,
  timestamp?: number,
): ChatMessage => ({
  id:
    id ??
    (typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : `${role}-${Date.now()}-${Math.random()}`),
  role,
  content,
  timestamp: timestamp ?? Date.now(),
});

function App() {
  const [locale, setLocale] = useState<Locale>(() => {
    if (typeof window === "undefined") return "zh";
    const stored = window.localStorage.getItem("ytsub_locale");
    return stored === "en" ? "en" : "zh";
  });
  const [theme, setTheme] = useState<"light" | "dark">(() => {
    if (typeof window === "undefined") return "light";
    return (localStorage.getItem("ytsub_theme") as "light" | "dark") ?? "light";
  });
  const [form, setForm] = useState({
    videoUrl: "",
    languageInput: "en",
    subtitleFormat: "srt" as SubtitleFormat,
    autoSubs: true,
    outputFilename: "",
    speaker: "",
    topic: "",
    template: defaultTemplates.zh,
    extraInstructions: "",
  });
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [result, setResult] = useState<SubtitleDownloadResponse | null>(null);
  const [playlistProgress, setPlaylistProgress] = useState<SubtitlePlaylistProgressResponse | null>(null);
  const [playlistPollingInterval, setPlaylistPollingInterval] = useState<ReturnType<typeof setInterval> | null>(null);
  const [sidebarWidth, setSidebarWidth] = useState<number>(() => {
    if (typeof window === "undefined") return 320;
    const stored = localStorage.getItem("ytsub_sidebar_width");
    return stored ? parseInt(stored, 10) : 320;
  });
  const [isResizing, setIsResizing] = useState(false);
  const [availableSubs, setAvailableSubs] = useState<SubtitleListResponse | null>(
    null,
  );
  const [subsStatus, setSubsStatus] = useState<StatusState>({ type: "idle" });
  const [videoQuality, setVideoQuality] = useState<VideoQuality>("best");
  const [videoStatus, setVideoStatus] = useState<StatusState>({ type: "idle" });
  const [videoJob, setVideoJob] = useState<VideoJobResponse | null>(null);
  const [subtitleRaw, setSubtitleRaw] = useState("");
  const [isSubtitleModalOpen, setIsSubtitleModalOpen] = useState(false);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([
    {
      id: "welcome",
      role: "assistant",
      content: welcomeMessages[locale],
      timestamp: Date.now(),
    },
  ]);
  const [chatInput, setChatInput] = useState("");
  const [chatProvider, setChatProvider] = useState(
    defaultProviderOption.value,
  );
  const [chatModel, setChatModel] = useState(
    defaultProviderOption.models[0]?.value ?? "",
  );
  const [temperature, setTemperature] = useState(0.2);
  const [chatLoading, setChatLoading] = useState(false);
  const chatWindowRef = useRef<HTMLDivElement | null>(null);
  const [isAdvancedModalOpen, setIsAdvancedModalOpen] = useState(false);
  const [expandedMessages, setExpandedMessages] = useState<Record<string, boolean>>({});
  const [apiKeyInput, setApiKeyInput] = useState("");
  const currentProvider = useMemo(
    () => providerOptions.find((item) => item.value === chatProvider),
    [chatProvider],
  );
  const availableModels = currentProvider?.models ?? [];
  const { toasts, pushToast, removeToast } = useToast();
  const videoPollRef = useRef<number | null>(null);
  const tr = useCallback(
    (zh: string, en: string) => (locale === "zh" ? zh : en),
    [locale],
  );

  // 清理播放列表轮询
  useEffect(() => {
    return () => {
      if (playlistPollingInterval) {
        clearInterval(playlistPollingInterval);
      }
    };
  }, [playlistPollingInterval]);

  // 保存侧边栏宽度
  useEffect(() => {
    if (typeof window !== "undefined") {
      localStorage.setItem("ytsub_sidebar_width", sidebarWidth.toString());
    }
  }, [sidebarWidth]);

  // 处理拖动调整侧边栏宽度
  const handleResizeStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    setIsResizing(true);
  }, []);

  useEffect(() => {
    if (!isResizing) return;

    const handleMouseMove = (e: MouseEvent) => {
      const newWidth = e.clientX - (window.innerWidth * 0.03); // 减去左侧padding
      const minWidth = 200;
      const maxWidth = Math.min(600, window.innerWidth * 0.6);
      setSidebarWidth(Math.max(minWidth, Math.min(maxWidth, newWidth)));
    };

    const handleMouseUp = () => {
      setIsResizing(false);
    };

    document.addEventListener("mousemove", handleMouseMove);
    document.addEventListener("mouseup", handleMouseUp);

    return () => {
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleMouseUp);
    };
  }, [isResizing]);

  const themeToggleTitle =
    theme === "light"
      ? tr("切换夜间模式", "Switch to dark mode")
      : tr("切换日间模式", "Switch to light mode");
  const ThemeToggleIcon = theme === "light" ? (
    <Moon size={18} strokeWidth={2} />
  ) : (
    <Sun size={18} strokeWidth={2} />
  );
  const languageToggleLabel = locale === "zh" ? "EN" : "中";
  const languageToggleTitle =
    locale === "zh" ? "Switch to English UI" : "切换到中文界面";

  const parsedLanguages = useMemo(
    () =>
      form.languageInput
        .split(/[,\\s]+/)
        .map((lang) => lang.trim())
        .filter(Boolean),
    [form.languageInput],
  );
  const formatOptions = useMemo(
    () =>
      subtitleFormats.map((format) => ({
        value: format.value,
        label: format.label[locale],
      })),
    [locale],
  );
  const videoQualityOptions = useMemo(
    () =>
      videoQualities.map((quality) => ({
        value: quality.value,
        label: quality.label[locale],
      })),
    [locale],
  );
  const resolveQualityLabel = useCallback(
    (value: VideoQuality) =>
      videoQualityOptions.find((option) => option.value === value)?.label ?? value,
    [videoQualityOptions],
  );
  const resolveModelLabel = useCallback(
    (modelId: string, providerId?: string) => {
      const provider = providerId
        ? providerOptions.find((p) => p.value === providerId)
        : currentProvider;
      const model = provider?.models.find((m) => m.value === modelId);
      return model ? model.label[locale] : modelId;
    },
    [locale, currentProvider],
  );
  const resolveProviderLabel = useCallback(
    (providerId: string) => {
      const provider = providerOptions.find((p) => p.value === providerId);
      return provider ? provider.label[locale] : providerId;
    },
    [locale],
  );
  const formatLanguageList = useCallback(
    (items: string[]) =>
      items.length
        ? items.join(locale === "zh" ? "、" : ", ")
        : tr("未设置", "Not set"),
    [locale, tr],
  );

  useEffect(() => {
    setAvailableSubs(null);
    setSubsStatus({ type: "idle" });
  }, [form.videoUrl]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("ytsub_theme", theme);
  }, [theme]);

  useEffect(() => {
    if (typeof window !== "undefined") {
      window.localStorage.setItem("ytsub_locale", locale);
    }
  }, [locale]);

  useEffect(() => {
    setForm((prev) => {
      if (locale === "en" && prev.template === defaultTemplates.zh) {
        return { ...prev, template: defaultTemplates.en };
      }
      if (locale === "zh" && prev.template === defaultTemplates.en) {
        return { ...prev, template: defaultTemplates.zh };
      }
      return prev;
    });
  }, [locale]);

  useEffect(() => {
    setChatMessages((prev) => {
      if (!prev.length) return prev;
      const first = prev[0];
      const otherLocale: Locale = locale === "zh" ? "en" : "zh";
      if (first.id === "welcome" && first.content === welcomeMessages[otherLocale]) {
        const updated = [...prev];
        updated[0] = { ...first, content: welcomeMessages[locale] };
        return updated;
      }
      return prev;
    });
  }, [locale]);

  useEffect(() => {
    chatWindowRef.current?.scrollTo({
      top: chatWindowRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [chatMessages]);

  useEffect(() => {
    if (currentProvider?.models?.[0]?.value) {
      setChatModel(currentProvider.models[0].value);
    } else {
      setChatModel("");
    }
  }, [chatProvider, currentProvider]);

  useEffect(() => {
    return () => {
      if (videoPollRef.current) {
        window.clearInterval(videoPollRef.current);
      }
    };
  }, []);

  // 开发环境下自动填充 API Key（仅开发阶段使用）
  useEffect(() => {
    if (!import.meta.env.DEV) {
      return;
    }
    const envKey = currentProvider?.devEnvKey;
    if (!envKey) {
      return;
    }
    const envRecord = import.meta.env as Record<string, string | undefined>;
    const envValue = envRecord[envKey];
    if (envValue) {
      setApiKeyInput(envValue);
    }
  }, [chatProvider, currentProvider]);

  const startVideoPolling = (jobId: string) => {
    if (videoPollRef.current) {
      window.clearInterval(videoPollRef.current);
    }
    videoPollRef.current = window.setInterval(() => {
      void fetchVideoStatus(jobId);
    }, 2000);
  };

  const stopVideoPolling = () => {
    if (videoPollRef.current) {
      window.clearInterval(videoPollRef.current);
      videoPollRef.current = null;
    }
  };

  const fetchPlaylistProgress = async (jobId: string) => {
    try {
      const progress = await requestJson<SubtitlePlaylistProgressResponse>(
        `/api/subtitles/playlist-progress/${jobId}`,
      );
      setPlaylistProgress(progress);
      
      // 如果已完成或失败，停止轮询
      if (progress.status === "completed" || progress.status === "failed") {
        if (playlistPollingInterval) {
          clearInterval(playlistPollingInterval);
          setPlaylistPollingInterval(null);
        }
        setIsSubmitting(false);
        if (progress.status === "completed") {
          pushToast("success", tr("播放列表字幕下载完成！", "Playlist subtitle download completed!"));
        }
      }
    } catch (error) {
      // 如果获取进度失败，可能是任务已完成或不存在
      if (playlistPollingInterval) {
        clearInterval(playlistPollingInterval);
        setPlaylistPollingInterval(null);
      }
      setIsSubmitting(false);
    }
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!form.videoUrl) {
      pushToast("error", tr("请先填写视频链接", "Please enter the video URL first"));
      return;
    }
    if (parsedLanguages.length === 0) {
      pushToast("error", tr("至少指定一种字幕语言", "Select at least one subtitle language"));
      return;
    }

    const payload: SubtitleDownloadRequest = {
      video_url: form.videoUrl,
      subtitle_languages: parsedLanguages,
      subtitle_format: form.subtitleFormat,
      prefer_auto_subs: form.autoSubs,
      output_filename: form.outputFilename || null,
      prompt: {
        template: form.template,
        speaker: form.speaker || tr("未知主讲人", "Unknown speaker"),
        topic: form.topic || tr("未指定主题", "Untitled topic"),
        extra_instructions: form.extraInstructions || null,
      },
    };

    setIsSubmitting(true);
    setResult(null);
    setPlaylistProgress(null);

    // 清除之前的轮询
    if (playlistPollingInterval) {
      clearInterval(playlistPollingInterval);
      setPlaylistPollingInterval(null);
    }

    try {
      const data = await postJson<SubtitleDownloadResponse | SubtitlePlaylistDownloadResponse>(
        "/api/subtitles/download",
        payload,
      );
      
      // 检查是否是播放列表响应
      if ("total_videos" in data && "job_id" in data) {
        // 这是播放列表响应
        const playlistData = data as SubtitlePlaylistDownloadResponse;
        setPlaylistProgress({
          job_id: playlistData.job_id,
          total_videos: playlistData.total_videos,
          completed: playlistData.completed,
          successful: playlistData.successful,
          failed: playlistData.failed,
          in_progress: playlistData.in_progress,
          status: playlistData.status,
          current_videos: [],
          results: playlistData.results,
        });
        
        // 如果还在运行，启动轮询
        if (playlistData.status === "running" || playlistData.status === "pending") {
          const interval = setInterval(() => {
            fetchPlaylistProgress(playlistData.job_id);
          }, 2000); // 每2秒轮询一次
          setPlaylistPollingInterval(interval);
        } else {
          setIsSubmitting(false);
          if (playlistData.status === "completed") {
            pushToast("success", tr("播放列表字幕下载完成！", "Playlist subtitle download completed!"));
          }
        }
      } else {
        // 单个视频响应
        const singleData = data as SubtitleDownloadResponse;
        setResult(singleData);
        const fileUrl = toPublicAssetUrl(singleData.subtitle_file);
        if (fileUrl) {
          const fileResponse = await fetch(fileUrl);
          if (fileResponse.ok) {
            const text = await fileResponse.text();
            setSubtitleRaw(text);
          } else {
            setSubtitleRaw("");
          }
        } else {
          setSubtitleRaw("");
        }
        setIsSubmitting(false);
        pushToast("success", tr("字幕处理完成，可以下载啦！", "Subtitles processed. Ready to download!"));
      }
    } catch (error) {
      const message =
        error instanceof ApiError
          ? error.message
          : error instanceof Error
            ? error.message
            : tr("未知错误，请稍后再试", "Unknown error, please try again.");
      pushToast("error", message);
      setIsSubmitting(false);
      if (playlistPollingInterval) {
        clearInterval(playlistPollingInterval);
        setPlaylistPollingInterval(null);
      }
    }
  };

  const handleFetchSubtitles = async () => {
    if (!form.videoUrl) {
      setSubsStatus({
        type: "error",
        message: tr("请先填写视频链接", "Please enter the video URL first"),
      });
      return;
    }
    setSubsStatus({ type: "loading", message: tr("正在列出可用字幕...", "Listing available subtitles...") });
    setAvailableSubs(null);
    try {
      const data = await postJson<SubtitleListResponse>("/api/subtitles/list", {
        video_url: form.videoUrl,
      });
      setAvailableSubs(data);
      const total = data.automatic.length + data.manual.length;
      setSubsStatus({
        type: "success",
        message: tr(
          `已找到 ${total} 条字幕轨道，可点击添加到下面的语言列表中`,
          `Found ${total} subtitle tracks. Click any language to add it below.`,
        ),
      });
      pushToast("info", tr("字幕轨道列表获取成功", "Subtitle tracks loaded successfully"));
    } catch (error) {
      const message =
        error instanceof ApiError && error.status === 404
          ? error.message ||
            tr(
              "未能列出字幕轨道，但仍可直接尝试自动字幕下载。",
              "No track list available, but you can still try automatic subtitles.",
            )
          : error instanceof ApiError
            ? error.message
            : error instanceof Error
              ? error.message
              : tr("未知错误，无法获取字幕列表", "Unknown error: unable to fetch subtitle list");
      pushToast("error", message);
    }
  };

  const handleVideoDownload = async () => {
    if (!form.videoUrl) {
      pushToast("error", tr("请先填写视频链接", "Please enter the video URL first"));
      return;
    }
    setVideoStatus({
      type: "loading",
      message: tr("任务已创建，正在排队...", "Task created, waiting in queue..."),
    });
    setVideoJob(null);
    try {
      const payload = {
        video_url: form.videoUrl,
        quality: videoQuality,
      };
      const data = await postJson<VideoJobResponse>(
        "/api/videos/download",
        payload,
      );
      setVideoJob(data);
      setVideoStatus({
        type: "loading",
        message: data.message ?? tr("视频下载中...", "Video download in progress..."),
      });
      startVideoPolling(data.job_id);
    } catch (error) {
      const message =
        error instanceof ApiError
          ? error.message
          : error instanceof Error
            ? error.message
            : tr("视频下载任务创建失败", "Failed to create video download task");
      setVideoStatus({ type: "error", message });
      pushToast("error", message);
    }
  };

  const fetchVideoStatus = async (jobId: string) => {
    try {
      const data = await requestJson<VideoJobResponse>(
        `/api/videos/status/${jobId}`,
      );
      setVideoJob(data);
      if (data.status === "completed") {
        stopVideoPolling();
        setVideoStatus({
          type: "success",
          message: data.message ?? tr("视频已准备就绪", "Video is ready"),
        });
        pushToast("success", tr("视频下载完成，可开始获取", "Video ready. You can download it now."));
      } else if (data.status === "failed") {
        stopVideoPolling();
        setVideoStatus({
          type: "error",
          message: data.message ?? tr("视频下载失败", "Video download failed"),
        });
        pushToast("error", data.message ?? tr("视频下载失败", "Video download failed"));
      } else {
        setVideoStatus({
          type: "loading",
          message: data.message ?? tr("视频处理中...", "Video is processing..."),
        });
      }
    } catch (error) {
      stopVideoPolling();
      const message =
        error instanceof ApiError
          ? error.message
          : error instanceof Error
            ? error.message
            : tr("视频状态查询失败", "Unable to fetch video status");
      setVideoStatus({ type: "error", message });
      pushToast("error", message);
    }
  };

  const handleAppendLanguage = (language: string) => {
    setForm((prev) => {
      const existing = prev.languageInput
        .split(/[,\\s]+/)
        .map((lang) => lang.trim())
        .filter(Boolean);
      if (existing.includes(language)) {
        return prev;
      }
      const next = [...existing, language];
      return { ...prev, languageInput: next.join(", ") };
    });
  };

  const handleSendMessage = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const content = chatInput.trim();
    if (!content) {
      return;
    }
    if (!apiKeyInput.trim()) {
      pushToast("error", tr("请先填写模型的 API Key", "Please enter the model API key"));
      return;
    }
    if (!chatModel) {
      pushToast("error", tr("请选择要调用的模型", "Please choose a model to call"));
      return;
    }
    const userMessage = createMessage("user", content);
    const assistantMessageId =
      typeof crypto !== "undefined" && "randomUUID" in crypto
        ? crypto.randomUUID()
        : `assistant-${Date.now()}-${Math.random()}`;
    const placeholderAssistant = createMessage(
      "assistant",
      "",
      assistantMessageId,
    );
    setChatMessages((prev) => [...prev, userMessage, placeholderAssistant]);
    setChatInput("");
    setChatLoading(true);
    try {
      const payload: SubtitleAnalysisRequest = {
        instructions: content,
        provider: chatProvider,
        api_key: apiKeyInput.trim(),
        base_url: currentProvider?.baseUrl ?? null,
        model: chatModel,
        temperature,
        stream: true,
        ...(result
          ? {
              job_id: result.job_id,
              subtitle_file: result.subtitle_file,
            }
          : {
              subtitle_text: content,
            }),
      };
      const response = await fetch(buildApiUrl("/api/subtitles/analyze"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        const errorText = await readError(response);
        throw new Error(errorText || tr("LLM 调用失败", "LLM request failed"));
      }
      const isStream =
        payload.stream &&
        response.body &&
        (response.headers.get("content-type") ?? "").includes("text/plain");
      const providerId =
        response.headers.get("x-llm-provider") ?? payload.provider;
      const modelId =
        response.headers.get("x-llm-model") ?? chatModel ?? "";
      const providerLabel = resolveProviderLabel(providerId);
      const modelLabel = modelId
        ? resolveModelLabel(modelId, providerId)
        : tr("未知模型", "Unknown model");
      const metaSuffix = `\n\n— ${tr("来自", "Powered by")} ${providerLabel} · ${modelLabel}`;

      if (isStream && response.body) {
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let accumulated = "";
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          if (value) {
            const chunk = decoder.decode(value, { stream: true });
            if (chunk) {
              accumulated += chunk;
              const snapshot = accumulated;
              setChatMessages((prev) =>
                prev.map((msg) =>
                  msg.id === assistantMessageId
                    ? { ...msg, content: snapshot }
                    : msg,
                ),
              );
            }
          }
        }
        const finalChunk = decoder.decode();
        if (finalChunk) {
          accumulated += finalChunk;
          setChatMessages((prev) =>
            prev.map((msg) =>
              msg.id === assistantMessageId
                ? { ...msg, content: accumulated }
                : msg,
            ),
          );
        }
        setChatMessages((prev) =>
          prev.map((msg) =>
            msg.id === assistantMessageId
              ? { ...msg, content: (msg.content || "") + metaSuffix }
              : msg,
          ),
        );
        return;
      }

      const data = (await response.json()) as SubtitleAnalysisResponse;
      setChatMessages((prev) =>
        prev.map((msg) =>
          msg.id === assistantMessageId
            ? {
                ...msg,
                content: `${data.assistant_message}\n\n— ${tr("来自", "Powered by")} ${data.provider} · ${data.model_used}`,
              }
            : msg,
        ),
      );
    } catch (error) {
      const message =
        error instanceof Error ? error.message : tr("聊天失败，请稍后重试", "Chat failed. Please try again later.");
      setChatMessages((prev) =>
        prev.map((msg) =>
          msg.id === assistantMessageId
            ? { ...msg, content: `⚠️ ${message}` }
            : msg,
        ),
      );
      pushToast("error", message);
    } finally {
      setChatLoading(false);
    }
  };

  const handleFillChatWithSubtitles = () => {
    if (!subtitleRaw.trim()) {
      pushToast("error", tr("暂无字幕内容可填充", "No subtitle content to insert"));
      return;
    }
    setChatInput(
      (prev) =>
        prev +
        (prev ? "\n\n" : "") +
        tr("请阅读以下字幕并按照我的指令整理：\n", "Please read the subtitles below and follow my instructions:\n") +
        subtitleRaw,
    );
    pushToast("success", tr("字幕已填充至聊天输入框", "Subtitles added to the chat input"));
  };

  const handleCopySubtitle = async () => {
    if (!subtitleRaw.trim()) {
      pushToast("error", tr("暂无字幕内容可复制", "No subtitle content to copy"));
      return;
    }
    await navigator.clipboard.writeText(subtitleRaw);
    pushToast("success", tr("字幕内容已复制", "Subtitles copied to clipboard"));
  };

  const handleOpenSubtitleModal = () => {
    if (!subtitleRaw.trim()) {
      pushToast("error", tr("暂无字幕内容可预览", "No subtitle content to preview"));
      return;
    }
    setIsSubtitleModalOpen(true);
  };

  const handleCloseSubtitleModal = () => setIsSubtitleModalOpen(false);

  const toggleMessageExpansion = (id: string) => {
    setExpandedMessages((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  return (
    <div className="page chat-shell">
      <ToastStack toasts={toasts} onDismiss={removeToast} />
      <aside className="control-column" style={{ width: `${sidebarWidth}px`, minWidth: `${sidebarWidth}px`, maxWidth: `${sidebarWidth}px` }}>
        <div className="top-controls">
          <button
            type="button"
            className="btn icon-btn ghost subtle"
            onClick={() => setTheme((prev) => (prev === "light" ? "dark" : "light"))}
            aria-label={themeToggleTitle}
            title={themeToggleTitle}
          >
            {ThemeToggleIcon}
          </button>
          <button
            type="button"
            className="btn ghost subtle language-toggle"
            onClick={() => setLocale((prev) => (prev === "zh" ? "en" : "zh"))}
            aria-label={languageToggleTitle}
            title={languageToggleTitle}
          >
            {languageToggleLabel}
          </button>
        </div>
        <div
          className="resize-handle"
          onMouseDown={handleResizeStart}
          style={{
            cursor: "col-resize",
            width: "4px",
            backgroundColor: "transparent",
            position: "absolute",
            right: "-2px",
            top: 0,
            bottom: 0,
            zIndex: 10,
          }}
        />
        <section className="panel form-panel">
          <h2>{tr("字幕抓取参数", "Subtitle Parameters")}</h2>
          <p className="subtitle compact">
            {tr(
              "填完链接与语言后即可抓取字幕；如需自定义提示词，请展开高级设置。",
              "Fill in the link and languages to pull subtitles. Open Advanced Settings for template tweaks.",
            )}
          </p>
          <form className="form" onSubmit={handleSubmit}>
            <label>
              {tr("YouTube 视频链接", "YouTube Video URL")}
              <div className="input-with-action">
              <input
                type="url"
                placeholder="https://www.youtube.com/watch?v=..."
                value={form.videoUrl}
                onChange={(event) =>
                  setForm((prev) => ({ ...prev, videoUrl: event.target.value }))
                }
                required
              />
                {form.videoUrl.trim() && (
                  <button
                    type="button"
                    className="btn icon-btn ghost subtle"
                    onClick={() => setForm((prev) => ({ ...prev, videoUrl: "" }))}
                    aria-label={tr("清除链接", "Clear URL")}
                    title={tr("清除", "Clear")}
                  >
                    <X size={16} strokeWidth={2} />
                  </button>
                )}
                <button
                  type="button"
                  className="btn icon-btn ghost subtle"
                  onClick={handleFetchSubtitles}
                  disabled={subsStatus.type === "loading"}
                  aria-label={tr("列出字幕", "List available subtitles")}
                  title={tr("列出字幕", "List available subtitles")}
                >
                  {subsStatus.type === "loading" ? (
                    <span className="spinner" aria-hidden="true" />
                  ) : (
                    <ListChecks size={16} strokeWidth={2} />
                  )}
                  <span className="sr-only">
                    {tr("列出字幕", "List available subtitles")}
                  </span>
                </button>
              </div>
            </label>
            {subsStatus.type !== "idle" && (
              <p className={`hint-line ${subsStatus.type}`}>{subsStatus.message}</p>
            )}

            <div className="field-row">
              <label>
                {tr("字幕语言（逗号或空格分隔）", "Subtitle languages (comma or space separated)")}
                <input
                  type="text"
                  value={form.languageInput}
                  onChange={(event) =>
                    setForm((prev) => ({
                      ...prev,
                      languageInput: event.target.value,
                    }))
                  }
                  placeholder="en, zh-Hans"
                />
              </label>
              <label>
                {tr("字幕格式", "Subtitle format")}
                <select
                  value={form.subtitleFormat}
                  onChange={(event) =>
                    setForm((prev) => ({
                      ...prev,
                      subtitleFormat: event.target.value as SubtitleFormat,
                    }))
                  }
                >
                  {formatOptions.map((format) => (
                    <option value={format.value} key={format.value}>
                      {format.label}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            {availableSubs && (
              <div className="subs-panel">
                <p className="small-muted">
                  {tr("点击语言即可插入到输入框", "Click a language to insert it below")}
                </p>
                <SubtitleSection
                  title={tr("自动字幕", "Automatic captions")}
                  tracks={availableSubs.automatic}
                  onPick={handleAppendLanguage}
                  emptyLabel={tr("未知格式", "Unknown format")}
                />
                <SubtitleSection
                  title={tr("人工字幕", "Human captions")}
                  tracks={availableSubs.manual}
                  onPick={handleAppendLanguage}
                  emptyLabel={tr("未知格式", "Unknown format")}
                />
              </div>
            )}

            <div className="field-row">
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={form.autoSubs}
                  onChange={(event) =>
                    setForm((prev) => ({
                      ...prev,
                      autoSubs: event.target.checked,
                    }))
                  }
                />
                {tr("使用自动生成字幕", "Prefer automatic captions")}
              </label>
              <label>
                {tr("自定义输出文件名", "Custom output file name")}
                <input
                  type="text"
                  placeholder={tr("可选，例如 ai-talk.srt", "Optional, e.g. ai-talk.srt")}
                  value={form.outputFilename}
                  onChange={(event) =>
                    setForm((prev) => ({
                      ...prev,
                      outputFilename: event.target.value,
                    }))
                  }
                />
              </label>
            </div>

            <p className="small-muted">
              {tr("当前语言：", "Current languages:")}
              {parsedLanguages.length
                ? parsedLanguages.join(locale === "zh" ? "、" : ", ")
                : tr("未设置", "Not set")}
            </p>

            <div className="advanced-bar">
              <button
                type="button"
                className="btn icon-btn ghost advanced-trigger"
                onClick={() => setIsAdvancedModalOpen(true)}
                aria-haspopup="dialog"
                aria-expanded={isAdvancedModalOpen}
                aria-label={tr("高级设置", "Advanced settings")}
                title={tr("高级设置", "Advanced settings")}
              >
                <Settings2 size={18} strokeWidth={2} />
                <span className="sr-only">{tr("高级设置", "Advanced settings")}</span>
              </button>
              <div className="advanced-meta" aria-hidden="true">
                <UserRound size={16} />
                <BookMarked size={16} />
                <Sparkles size={16} />
              </div>
            </div>

            <button
              className="btn primary"
              type="submit"
              disabled={isSubmitting}
            >
              {isSubmitting
                ? tr("处理中...", "Processing...")
                : tr("生成字幕与提示词", "Generate subtitles & prompts")}
            </button>
          </form>

        {playlistProgress && (
          <div className="result-stack">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
              <h3 style={{ margin: 0 }}>{tr("播放列表下载进度", "Playlist Download Progress")}</h3>
              <button
                className="btn ghost"
                onClick={() => {
                  setPlaylistProgress(null);
                  if (playlistPollingInterval) {
                    clearInterval(playlistPollingInterval);
                    setPlaylistPollingInterval(null);
                  }
                }}
                style={{ fontSize: "0.85rem", padding: "6px 12px" }}
              >
                {tr("清除", "Clear")}
              </button>
            </div>
            <div className="result-card">
              <div style={{ width: "100%" }}>
                <div className="progress-header">
                  <span className="progress-label">
                    {playlistProgress.completed} / {playlistProgress.total_videos}
                  </span>
                  <div className="progress-track">
                    <div
                      className="progress-thumb"
                      style={{
                        width: `${(playlistProgress.completed / playlistProgress.total_videos) * 100}%`,
                      }}
                    />
                  </div>
                </div>
                <div style={{ marginTop: "12px", display: "flex", gap: "16px", flexWrap: "wrap" }}>
                  <span className="small-muted">
                    {tr("成功：", "Successful:")} {playlistProgress.successful}
                  </span>
                  <span className="small-muted">
                    {tr("失败：", "Failed:")} {playlistProgress.failed}
                  </span>
                  <span className="small-muted">
                    {tr("进行中：", "In Progress:")} {playlistProgress.in_progress}
                  </span>
                </div>
                {playlistProgress.current_videos.length > 0 && (
                  <div style={{ marginTop: "12px" }}>
                    <p className="small-muted">
                      {tr("当前下载：", "Currently downloading:")}
                    </p>
                    <ul style={{ marginTop: "8px", paddingLeft: "20px" }}>
                      {playlistProgress.current_videos.map((url, idx) => (
                        <li key={idx} className="small-muted" style={{ wordBreak: "break-all" }}>
                          {url}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {playlistProgress.status === "completed" && playlistProgress.results.length > 0 && (
                  <div style={{ marginTop: "16px" }}>
                    <p className="label">{tr("下载结果", "Download Results")}</p>
                    <div style={{ display: "flex", flexDirection: "column", gap: "8px", marginTop: "8px" }}>
                      {playlistProgress.results.map((item, idx) => (
                        <div
                          key={idx}
                          style={{
                            padding: "8px 12px",
                            borderRadius: "8px",
                            background: item.subtitle_file
                              ? "rgba(34, 197, 94, 0.1)"
                              : "rgba(239, 68, 68, 0.1)",
                            border: `1px solid ${item.subtitle_file ? "rgba(34, 197, 94, 0.3)" : "rgba(239, 68, 68, 0.3)"}`,
                          }}
                        >
                          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                            <span className="small-muted" style={{ flex: 1, wordBreak: "break-all" }}>
                              {item.video_title || item.video_url || `Video ${idx + 1}`}
                            </span>
                            {item.subtitle_file ? (
                              <a
                                href={toPublicAssetUrl(item.subtitle_file) ?? undefined}
                                target="_blank"
                                rel="noreferrer"
                                style={{ marginLeft: "12px", color: "var(--brand)" }}
                              >
                                {tr("下载", "Download")}
                              </a>
                            ) : (
                              <span className="small-muted" style={{ marginLeft: "12px" }}>
                                {item.prompt_preview || tr("失败", "Failed")}
                              </span>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {result && (
            <div className="result-stack">
              <h3>{tr("最新字幕", "Latest subtitles")}</h3>
            <div className="result-card">
              <div>
                  <p className="label">{tr("字幕文件", "Subtitle file")}</p>
                <a
                    href={toPublicAssetUrl(result.subtitle_file) ?? undefined}
                  target="_blank"
                  rel="noreferrer"
                >
                    {tr("下载", "Download")} {result.subtitle_format.toUpperCase()}{" "}
                    {tr("文件", "file")}
                </a>
                <p className="small-muted">
                    {tr("语言：", "Languages:")}
                    {formatLanguageList(result.subtitle_languages)}
                </p>
              </div>
              {result.prompt_file && (
                <div>
                    <p className="label">{tr("提示词文件", "Prompt file")}</p>
                  <a
                      href={toPublicAssetUrl(result.prompt_file) ?? undefined}
                    target="_blank"
                    rel="noreferrer"
                  >
                      {tr("下载 GPT 提示词", "Download GPT prompt")}
                  </a>
                </div>
              )}
            </div>

              <div className="result-actions">
                <button className="btn ghost" onClick={handleFillChatWithSubtitles}>
                  {tr("填充到聊天", "Insert into chat")}
                </button>
                <button className="btn ghost" onClick={handleOpenSubtitleModal}>
                  👁 {tr("预览字幕", "Preview subtitles")}
                </button>
                <button className="btn ghost" onClick={handleCopySubtitle}>
                  {tr("复制字幕", "Copy subtitles")}
                </button>
              </div>
            </div>
          )}

          <div className="video-download-block">
            <div className="video-header">
              <h3>{tr("视频下载", "Video download")}</h3>
              <p className="small-muted">
                {tr(
                  "默认下载最高画质，可选择目标画质后点击按钮。",
                  "Default to best quality, or pick a target resolution before downloading.",
                )}
              </p>
            </div>
            <div className="video-controls">
              <label>
                {tr("目标画质", "Target quality")}
                <select
                  value={videoQuality}
                  onChange={(event) =>
                    setVideoQuality(event.target.value as VideoQuality)
                  }
                >
                  {videoQualityOptions.map((quality) => (
                    <option key={quality.value} value={quality.value}>
                      {quality.label}
                    </option>
                  ))}
                </select>
              </label>
              <button
                type="button"
                className="btn primary"
                onClick={handleVideoDownload}
                disabled={videoStatus.type === "loading" || !form.videoUrl.trim()}
              >
                {videoStatus.type === "loading"
                  ? tr("下载中...", "Downloading...")
                  : tr("下载视频", "Download video")}
                  </button>
            </div>
            {videoStatus.type !== "idle" && (
              <p className={`hint-line ${videoStatus.type}`}>
                {videoStatus.message}
              </p>
            )}
            {videoJob && (
              <>
                <div className="video-progress">
                  <div className="progress-header">
                    <span className="progress-label">
                      {videoJob.status === "completed"
                        ? tr("完成", "Done")
                        : videoJob.status === "failed"
                          ? tr("失败", "Failed")
                          : `${videoJob.progress_percent}%`}
                    </span>
                    <span className="small-muted">
                      {videoJob.message ?? tr("视频处理中...", "Video is processing...")}
                    </span>
                  </div>
                  <div className="progress-track">
                    <div
                      className="progress-thumb"
                      style={{ width: `${videoJob.progress_percent}%` }}
                    />
                  </div>
                </div>

                {videoJob.status === "completed" && (
                  <div className="result-card">
                    <div>
                      <p className="label">{tr("视频文件", "Video file")}</p>
                      <p className="small-muted">
                        {tr("画质：", "Quality:")}
                        {resolveQualityLabel(videoJob.quality)} · {tr("大小：", "Size:")}
                        {videoJob.file_size_human ?? "--"}
                      </p>
                      {videoJob.format_note && (
                        <p className="small-muted">{videoJob.format_note}</p>
                      )}
                    </div>
                    <div className="video-actions">
                      {videoJob.fetch_url && (
                        <a
                          className="btn primary"
                          href={toPublicAssetUrl(videoJob.fetch_url) ?? undefined}
                          target="_blank"
                          rel="noreferrer"
                        >
                          {tr("获取视频", "Fetch video")}
                        </a>
                      )}
                      {videoJob.video_file && (
                        <a
                          className="btn ghost"
                          href={toPublicAssetUrl(videoJob.video_file) ?? undefined}
                          target="_blank"
                          rel="noreferrer"
                        >
                          {tr("静态链接", "Static link")}
                        </a>
                      )}
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        </section>
      </aside>

        <section className="chat-column">
          <div className="chat-header">
            <div>
              <h2>{tr("GPT 字幕助手", "GPT Subtitle Assistant")}</h2>
              <p>
                {tr(
                  "结合最新下载的字幕，发起提问或整理需求（例如“总结成 3 个要点并列出行动项”）。",
                  "Use the downloaded subtitles to ask questions or request structured summaries (e.g., “Give me 3 bullet points and action items”).",
                )}
              </p>
            </div>
            <div className="chat-controls">
              <label>
                {tr("模型服务商", "Provider")}
                <select
                  value={chatProvider}
                  onChange={(event) => setChatProvider(event.target.value)}
                >
                  {providerOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label[locale]}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                {tr("模型", "Model")}
                <select
                  value={chatModel}
                  onChange={(event) => setChatModel(event.target.value)}
                >
                  {availableModels.length === 0 ? (
                    <option value="">
                      {tr("请先选择模型提供方", "Select a provider first")}
                    </option>
                  ) : (
                    availableModels.map((model) => (
                      <option key={model.value} value={model.value}>
                        {model.label[locale]}
                      </option>
                    ))
                  )}
                </select>
              </label>
              <label>
                API Key
                <input
                  type="password"
                  placeholder={tr("仅保存在本地", "Stored only on this device")}
                  value={apiKeyInput}
                  onChange={(event) => setApiKeyInput(event.target.value)}
                />
              </label>
              <label>
                {tr("温度", "Temperature")}
                <div className="temperature-control">
                  <input
                    type="range"
                    min={0}
                    max={1}
                    step={0.1}
                    value={temperature}
                    onChange={(event) =>
                      setTemperature(Number(event.target.value))
                    }
                  />
                  <span>{temperature.toFixed(1)}</span>
                </div>
              </label>
            </div>
          </div>

        <div className="chat-window" ref={chatWindowRef}>
          {chatMessages.map((message) => {
            const isUser = message.role === "user";
            const content = message.content ?? "";
            const expanded = expandedMessages[message.id];
            const shouldClamp =
              isUser && content.length > MESSAGE_SNIPPET_LIMIT;
            const displayText =
              shouldClamp && !expanded
                ? `${content.slice(0, MESSAGE_SNIPPET_LIMIT)}…`
                : content;
            const bubbleContentClass = `bubble-content${
              shouldClamp && !expanded ? " clamped" : ""
            }`;
            const bubbleBody = message.role === "assistant" ? (
              <ReactMarkdown
                className="bubble-markdown"
                remarkPlugins={markdownRemarkPlugins as unknown as any}
                rehypePlugins={markdownRehypePlugins as unknown as any}
              >
                {displayText}
              </ReactMarkdown>
            ) : (
              <p className={bubbleContentClass}>{displayText}</p>
            );
            return (
              <div
                key={message.id}
                className={`chat-bubble ${message.role}`}
              >
                <div className="bubble-meta">
                  <span>{message.role === "assistant" ? "GPT" : tr("我", "Me")}</span>
                  <time>{new Date(message.timestamp).toLocaleTimeString()}</time>
                </div>
                {bubbleBody}
                {shouldClamp && (
                  <button
                    type="button"
                    className="btn ghost subtle bubble-toggle"
                    onClick={() => toggleMessageExpansion(message.id)}
                  >
                    {expanded ? tr("收起", "Collapse") : tr("展开", "Expand")}
                  </button>
                )}
              </div>
            );
          })}
        </div>

        <form className="chat-composer" onSubmit={handleSendMessage}>
          <div className="textarea-wrapper">
            <textarea
              rows={3}
              placeholder={tr(
                "发送需求或问题，如：请总结这段文本 / 列出行动项",
                "Type your request, e.g. \"Summarize this text / list action items\".",
              )}
              value={chatInput}
              onChange={(event) => setChatInput(event.target.value)}
            />
            {chatInput.trim() && (
              <button
                type="button"
                className="clear-input-btn"
                onClick={() => setChatInput("")}
                aria-label={tr("清除输入", "Clear input")}
                title={tr("清除", "Clear")}
              >
                <X size={16} strokeWidth={2} />
              </button>
            )}
          </div>
          <div className="composer-footer">
            <span className="small-muted">
              {tr("Shift + Enter 换行", "Shift + Enter for new line")}
            </span>
            <button
              className="btn primary icon-btn"
              type="submit"
              disabled={chatLoading}
              aria-label={chatLoading ? tr("生成中", "Generating") : tr("发送消息", "Send message")}
              title={chatLoading ? tr("生成中...", "Generating...") : tr("发送", "Send")}
            >
              {chatLoading ? (
                <span className="spinner light" aria-hidden="true" />
              ) : (
                <SendHorizontal size={18} strokeWidth={2} />
              )}
            </button>
          </div>
        </form>
          </section>

      {isSubtitleModalOpen && (
        <div className="modal-overlay" onClick={handleCloseSubtitleModal}>
          <div
            className="modal-content"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="modal-header">
              <h3>{tr("字幕预览", "Subtitle preview")}</h3>
              <button className="btn ghost" onClick={handleCloseSubtitleModal}>
                ✕
              </button>
            </div>
            <div className="modal-body">
              <pre>{subtitleRaw || tr("暂无字幕内容", "No subtitle content yet")}</pre>
            </div>
          </div>
        </div>
      )}

      {isAdvancedModalOpen && (
        <div className="modal-overlay" onClick={() => setIsAdvancedModalOpen(false)}>
          <div
            className="modal-content"
            onClick={(event) => event.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-label={tr("高级设置", "Advanced settings")}
          >
            <div className="modal-header">
              <h3>{tr("高级设置", "Advanced settings")}</h3>
              <button
                className="btn ghost icon-btn"
                onClick={() => setIsAdvancedModalOpen(false)}
                aria-label={tr("关闭高级设置", "Close advanced settings")}
              >
                ✕
              </button>
            </div>
            <div className="modal-body advanced-modal-body">
            <div className="field-row">
              <label>
                  {tr("主讲人", "Speaker")}
                <input
                  type="text"
                    placeholder={tr("可选", "Optional")}
                  value={form.speaker}
                  onChange={(event) =>
                    setForm((prev) => ({ ...prev, speaker: event.target.value }))
                  }
                />
              </label>
              <label>
                  {tr("主题", "Topic")}
                <input
                  type="text"
                    placeholder={tr("可选", "Optional")}
                  value={form.topic}
                  onChange={(event) =>
                    setForm((prev) => ({ ...prev, topic: event.target.value }))
                  }
                />
              </label>
            </div>

            <label>
                {tr(
                  "模板正文（支持 {speaker}, {topic}, {subtitle_body}）",
                  "Template body (supports {speaker}, {topic}, {subtitle_body})",
                )}
              <textarea
                  rows={6}
                value={form.template}
                onChange={(event) =>
                  setForm((prev) => ({ ...prev, template: event.target.value }))
                }
              />
            </label>

            <label>
                {tr("额外提示", "Additional instructions")}
              <textarea
                rows={3}
                  placeholder={tr(
                    "例如输出 Notion 表格、突出行动列表等",
                    "e.g. create a Notion table, highlight action items, etc.",
                  )}
                value={form.extraInstructions}
                onChange={(event) =>
                  setForm((prev) => ({
                    ...prev,
                    extraInstructions: event.target.value,
                  }))
                }
              />
            </label>
            </div>
              </div>
                </div>
              )}
            </div>
  );
}

export default App;

interface SubtitleSectionProps {
  title: string;
  tracks: SubtitleListResponse["automatic"];
  onPick: (language: string) => void;
  emptyLabel: string;
}

function SubtitleSection({ title, tracks, onPick, emptyLabel }: SubtitleSectionProps) {
  if (tracks.length === 0) {
    return null;
  }
  return (
    <div className="subs-section">
      <h3>{title}</h3>
      <div className="subs-grid">
        {tracks.map((track: SubtitleTrack) => (
          <button
            type="button"
            key={`${title}-${track.language}`}
            className="subs-pill"
            onClick={() => onPick(track.language)}
          >
            <span>{track.language}</span>
            <small>{track.formats.join(", ") || emptyLabel}</small>
                  </button>
        ))}
                </div>
    </div>
  );
}

