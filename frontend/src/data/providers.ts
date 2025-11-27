export type Locale = "zh" | "en";

export type ProviderModel = {
  value: string;
  label: Record<Locale, string>;
  contextWindow?: string;
  note?: string;
};

export type ProviderOption = {
  value: string;
  label: Record<Locale, string>;
  baseUrl?: string;
  docsUrl?: string;
  devEnvKey?: string;
  models: ProviderModel[];
};

export const DEFAULT_PROVIDER_ID = "deepseek";

export const providerOptions: ProviderOption[] = [
  {
    value: "openai",
    label: { zh: "OpenAI", en: "OpenAI" },
    devEnvKey: "VITE_OPENAI_API_KEY",
    docsUrl: "https://platform.openai.com/docs/models",
    models: [
      { value: "gpt-4.1", label: { zh: "GPT-4.1 · 旗舰推理", en: "GPT-4.1 · Flagship reasoning" } },
      { value: "gpt-4.1-mini", label: { zh: "GPT-4.1 Mini · 快速/平衡", en: "GPT-4.1 Mini · Fast/balanced" } },
      { value: "gpt-4o", label: { zh: "GPT-4o · 全模态", en: "GPT-4o · Omni multimodal" } },
      { value: "gpt-4o-mini", label: { zh: "GPT-4o Mini · 轻量全模态", en: "GPT-4o Mini · Lightweight omni" } },
      { value: "gpt-4o-mini-128k", label: { zh: "GPT-4o Mini 128k · 长上下文", en: "GPT-4o Mini 128k · Long context" } },
      { value: "o4-mini", label: { zh: "o4-mini · 最新轻量推理", en: "o4-mini · Latest lightweight reasoning" } },
      { value: "gpt-3.5-turbo-0125", label: { zh: "GPT-3.5 Turbo 0125 · 旧版", en: "GPT-3.5 Turbo 0125 · Legacy" } },
    ],
  },
  {
    value: "deepseek",
    label: { zh: "DeepSeek", en: "DeepSeek" },
    baseUrl: "https://api.deepseek.com",
    devEnvKey: "VITE_DEEPSEEK_API_KEY",
    docsUrl: "https://platform.deepseek.com/docs",
    models: [
      { value: "deepseek-chat", label: { zh: "DeepSeek-Chat · 通用对话", en: "DeepSeek-Chat · General purpose" } },
      { value: "deepseek-reasoner", label: { zh: "DeepSeek-Reasoner · CoT 强化", en: "DeepSeek-Reasoner · CoT enhanced" } },
    ],
  },
  {
    value: "doubao",
    label: { zh: "豆包 · 字节火山", en: "Doubao · ByteDance VolcEngine" },
    baseUrl: "https://ark.cn-beijing.volces.com/api/v3",
    devEnvKey: "VITE_DOUBAO_API_KEY",
    docsUrl: "https://www.volcengine.com/docs/82379",
    models: [
      { value: "doubao-pro-128k", label: { zh: "Doubao-pro-128k · 高准确/长上下文", en: "Doubao-pro-128k · High accuracy/Long context" } },
      { value: "doubao-pro-32k", label: { zh: "Doubao-pro-32k · 主力生产", en: "Doubao-pro-32k · Production ready" } },
      { value: "doubao-lite-4k", label: { zh: "Doubao-lite-4k · 经济型", en: "Doubao-lite-4k · Cost-effective" } },
    ],
  },
  {
    value: "zhipu",
    label: { zh: "智谱 GLM", en: "Zhipu GLM" },
    baseUrl: "https://open.bigmodel.cn/api/paas/v4",
    devEnvKey: "VITE_ZHIPU_API_KEY",
    docsUrl: "https://bigmodel.cn/dev/api",
    models: [
      { value: "glm-4", label: { zh: "GLM-4 · 旗舰", en: "GLM-4 · Flagship" } },
      { value: "glm-4-air", label: { zh: "GLM-4-Air · 高性价比", en: "GLM-4-Air · High value" } },
      { value: "glm-4-flash", label: { zh: "GLM-4-Flash · 极速", en: "GLM-4-Flash · Ultra fast" } },
      { value: "glm-4-long", label: { zh: "GLM-4-Long · 1M 上下文", en: "GLM-4-Long · 1M context" } },
    ],
  },
  {
    value: "spark",
    label: { zh: "讯飞星火", en: "iFlytek Spark" },
    baseUrl: "https://spark-api.xf-yun.com/v1",
    devEnvKey: "VITE_SPARK_API_KEY",
    docsUrl: "https://www.xfyun.cn/doc/spark/",
    models: [
      { value: "spark-4.0-ultra", label: { zh: "Spark 4.0 Ultra · 全量能力", en: "Spark 4.0 Ultra · Full capabilities" } },
      { value: "spark-4.0-max", label: { zh: "Spark 4.0 Max · 高性能", en: "Spark 4.0 Max · High performance" } },
      { value: "spark-pro", label: { zh: "Spark Pro · 通用增强", en: "Spark Pro · Enhanced general" } },
      { value: "spark-lite", label: { zh: "Spark Lite · 轻量快速", en: "Spark Lite · Lightweight & fast" } },
    ],
  },
  {
    value: "grok",
    label: { zh: "xAI Grok", en: "xAI Grok" },
    baseUrl: "https://api.x.ai/v1",
    devEnvKey: "VITE_GROK_API_KEY",
    docsUrl: "https://docs.x.ai/docs",
    models: [
      { value: "grok-2", label: { zh: "Grok-2 · 最新旗舰", en: "Grok-2 · Latest flagship" } },
      { value: "grok-1.5", label: { zh: "Grok-1.5 · 扩展上下文", en: "Grok-1.5 · Extended context" } },
      { value: "grok-1.5-mini", label: { zh: "Grok-1.5 Mini · 高速模式", en: "Grok-1.5 Mini · High speed" } },
    ],
  },
  {
    value: "gemini",
    label: { zh: "Google Gemini", en: "Google Gemini" },
    baseUrl: "https://generativelanguage.googleapis.com/v1beta",
    devEnvKey: "VITE_GEMINI_API_KEY",
    docsUrl: "https://ai.google.dev/models/gemini",
    models: [
      { value: "gemini-1.5-pro", label: { zh: "Gemini 1.5 Pro · 1M tokens", en: "Gemini 1.5 Pro · 1M tokens" } },
      { value: "gemini-1.5-flash", label: { zh: "Gemini 1.5 Flash · 高性价比", en: "Gemini 1.5 Flash · High value" } },
      { value: "gemini-1.0-pro", label: { zh: "Gemini 1.0 Pro · 稳定版", en: "Gemini 1.0 Pro · Stable" } },
      { value: "gemini-1.0-flash", label: { zh: "Gemini 1.0 Flash · 经济型", en: "Gemini 1.0 Flash · Cost-effective" } },
    ],
  },
];


