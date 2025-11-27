export type SubtitleFormat = "srt" | "vtt" | "ass" | "json3" | "ttml";
export type VideoQuality =
  | "best"
  | "2160p"
  | "1440p"
  | "1080p"
  | "720p"
  | "480p"
  | "360p"
  | "240p"
  | "144p";

export interface PromptPayload {
  template?: string | null;
  speaker?: string;
  topic?: string;
  extra_instructions?: string | null;
}

export interface SubtitleDownloadRequest {
  video_url: string;
  subtitle_languages: string[];
  subtitle_format: SubtitleFormat;
  prefer_auto_subs: boolean;
  output_filename?: string | null;
  prompt?: PromptPayload | null;
}

export interface SubtitleDownloadResponse {
  job_id: string;
  created_at: string;
  subtitle_format: SubtitleFormat;
  subtitle_languages: string[];
  subtitle_file: string;
  prompt_file?: string | null;
  prompt_preview?: string | null;
}

export interface SubtitleTrack {
  language: string;
  formats: string[];
  is_automatic: boolean;
}

export interface SubtitleListResponse {
  automatic: SubtitleTrack[];
  manual: SubtitleTrack[];
}

export interface SubtitleAnalysisRequest {
  job_id?: string | null;
  subtitle_file?: string | null;
  subtitle_text?: string | null;
  instructions: string;
  provider: string;
  api_key?: string | null;
  base_url?: string | null;
  model?: string | null;
  temperature?: number;
  stream?: boolean;
}

export interface SubtitleAnalysisResponse {
  assistant_message: string;
  model_used: string;
  provider: string;
}

export interface VideoDownloadRequest {
  video_url: string;
  quality: VideoQuality;
  output_filename?: string | null;
}

export interface VideoDownloadResponse {
  job_id: string;
  created_at: string;
  quality: VideoQuality;
  video_file: string;
  filename: string;
  file_size: number;
  file_size_human: string;
  format_note?: string | null;
}

export type VideoJobStatus = "pending" | "running" | "completed" | "failed";

export interface VideoJobResponse {
  job_id: string;
  status: VideoJobStatus;
  progress_percent: number;
  message?: string | null;
  quality: VideoQuality;
  video_file?: string | null;
  filename?: string | null;
  file_size?: number | null;
  file_size_human?: string | null;
  format_note?: string | null;
  fetch_url?: string | null;
  created_at: string;
  updated_at: string;
}

