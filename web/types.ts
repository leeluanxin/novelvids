export enum AssetTypeEnum {
  PERSON = 1,
  SCENE = 2,
  ITEM = 3,
  GENERAL = 4,
}

export enum TaskStatusEnum {
  PENDING = 1,
  PROCESSING = 2,
  COMPLETED = 3,
  FAILED = 4,
  CANCELLED = 5,
  QUEUED = 6,
}

export enum VideoModelTypeEnum {
  VIDU_Q2 = 1,
  SORA_2 = 2,
  SEEDANCE = 3,
  VEO_3 = 4,
}

export type InvocationType = 'api' | 'cli'

export type StyleSource = 'builtin' | 'custom'

export interface StyleBinding {
  id: string;
  name: string;
  source: StyleSource;
  builtin_key?: 'reference-default' | 'storyboard-default';
  positive_prompt?: string;
  reference_image?: string;
}

export interface Novel {
  id: number;
  name: string;
  author?: string;
  description?: string;
  cover?: string;
  total_chapters?: number;
  content?: string;
  style?: StyleBinding;
  created_at: string;
  updated_at: string;
}

export interface Chapter {
  id: number;
  novel_id: number;
  number: number;
  name: string;
  content?: string;
  status?: TaskStatusEnum;
  workflow_status?: number;
  created_at: string;
  updated_at: string;
}

export interface Asset {
  id: number;
  novel_id: number;
  asset_type: AssetTypeEnum;
  canonical_name: string;
  aliases?: string[];
  description?: string;
  base_traits?: string;
  main_image?: string;
  angle_image_1?: string;
  angle_image_2?: string;
  audio_url?: string;
  audio_duration?: number;
  video_url?: string;
  video_duration?: number;
  is_global?: boolean;
  created_at: string;
  updated_at: string;
}

export interface Scene {
  id: number;
  chapter_id?: number;
  sequence: number;
  description?: string;
  prompt?: string;
  duration?: number;
  status?: TaskStatusEnum;
  asset_ids?: number[];
  assets?: Asset[];
  created_at: string;
  updated_at: string;
}

export interface Video {
  id: number;
  scene_id: number;
  model_type: VideoModelTypeEnum;
  url?: string;
  external_task_id?: string;
  status: TaskStatusEnum;
  progress?: number;
  metadata?: Record<string, any>;
  created_at: string;
  updated_at: string;
}

export interface VideoGeneratePayload {
  scene_id: number;
  model_type: VideoModelTypeEnum;
  model_version?: string;
}

export interface ChapterVideoItem {
  scene_id: number;
  sequence: number;
  description?: string;
  duration?: number;
  video: {
    id: number;
    url?: string;
    status: number;
    model_type: number;
  } | null;
}

export interface VideoMergeOut {
  chapter_id: number;
  merged_url: string;
  video_count: number;
  total_duration: number;
}

export interface AiTask {
  id: string;
  task_type: number;
  status: TaskStatusEnum;
  error_message?: string;
  created_at: string;
}

export interface ScenePromptPreview {
  system_prompt: string;
  storyboard_style?: StyleBinding;
}

export interface SceneGeneratePayload {
  chapter_id: number;
  system_prompt_override?: string;
}

export interface AiModelConfig {
  id: number;
  task_type: number;
  name: string;
  invocation_type: InvocationType;
  base_url?: string;
  api_key?: string;
  model?: string;
  cli_command?: string;
  is_active: boolean;
  concurrency: number;
  created_at: string;
  updated_at: string;
}

export interface EnumItem {
  value: number;
  label: string;
}

export interface AllEnums {
  [key: string]: EnumItem[];
}

// API Responses
export interface Pagination {
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface PaginationResponse<T> {
  code: number;
  message: string;
  data: {
    items: T[];
    pagination: Pagination;
  };
}

export interface SingleResponse<T> {
  code: number;
  message: string;
  data: T;
}

export interface StylePreset {
  id: string;
  name: string;
  positive_prompt: string;
  reference_image?: string;
  source: StyleSource;
  builtin_key?: 'reference-default' | 'storyboard-default';
  created_at?: string;
  updated_at?: string;
}
