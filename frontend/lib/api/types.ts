/**
 * 后端接口类型（与阶段 1 后端真实契约逐字对应）
 * 参考：docs/阶段开发文档.md 第 5 节
 */

export type CropBox = { x: number; y: number; w: number; h: number };

/** 鞋身文字的定位信息（文字兜底贴合用；box 为相对体检裁切图的归一化 [x,y,w,h]） */
export type TextStamp = {
  text: string;
  position: string;
  box: [number, number, number, number] | null;
};

export type InspectTier = "ok" | "not_shoe" | "multi" | "uncertain";

/** POST /inspect 的响应（前端只负责渲染，不猜后端规则） */
export type InspectResponse = {
  ok: boolean;
  tier: InspectTier;
  message: string;
  hint: string;
  crop: CropBox | null;
  image: { width: number; height: number };
  subject: { status: string; count: number };
  detail: {
    brand: string;
    model_name: string;
    colorway: string;
    display_name: string;
    logo_type: string;
    logo_position: string;
    logo_fill_required: boolean;
    texts: string[];
    text_stamps: TextStamp[];
    shoe_count: number;
    confidence: number;
  };
};

/** POST /tasks/upload 的请求体（体检结论由 /inspect 原样带回） */
export type UploadTaskPayload = {
  image_base64: string;
  crop: CropBox;
  inspect: {
    display_name: string;
    brand: string;
    model_name: string;
    colorway: string;
    logo_type: string;
    logo_position: string;
    logo_fill_required: boolean;
    texts: string[];
    text_stamps: TextStamp[];
    shoe_count: number;
  };
  style_id?: string;
};

export type TaskState =
  | "created"
  | "resolving"
  | "searching_source"
  | "model_not_found"
  | "resolve_failed"
  | "awaiting_source_confirm"
  | "preprocessing"
  | "generating"
  | "refining"
  | "verifying"
  | "interrupted"
  | "awaiting_effect_confirm"
  | "archiving"
  | "archived"
  | "failed"
  | "cancelled";

export type SourceMode = "single" | "model_only" | "choose";

export type ModelCandidate = { name: string; reason?: string };

export type ResolveInfo = {
  normalized: string;
  brand: string;
  confidence: number;
  exists: boolean;
  candidates: ModelCandidate[];
  note: string;
};

export type SourceCandidate = {
  index: number;
  provider: string;
  url: string | null;
  width: number | null;
  height: number | null;
  credit: string;
  /** 预筛结果（后端视觉质检给出，用于解释"为什么推荐这张"） */
  screen_score?: number;
  screen_reason?: string;
  screen_usable?: boolean;
  blur?: string | null;
  watermark?: string | null;
  shape?: string | null;
};

export type Artwork = {
  attempt: number;
  url: string;
  score: number | null;
  passed: boolean | null;
  issues: string[];
};

export type Quality = {
  score: number | null;
  attempts: number;
  checks: Record<string, number>;
  issues: string[];
  verdict: string | null;
  best_attempt: number | null;
  /** 自检没完全通过时给用户看的一句话（不含细节；细节在 checks/issues 里，仅内部用） */
  note: string;
};

export type TaskOut = {
  task_id: string;
  state: TaskState;
  query: string;
  style_id: string;
  created_at: string;
  updated_at: string;
  progress: { step?: string; label?: string; percent?: number };
  normalize: ResolveInfo | null;
  source_candidates: SourceCandidate[];
  source_mode: SourceMode;
  recommended_index: number;
  source_screen: { usable?: boolean; criteria?: string };
  selected_index: number | null;
  artworks: Artwork[];
  current_artwork_url: string | null;
  /** 当前展示的是第几次生成；其余几次作为历史稿列出 */
  current_attempt: number | null;
  /** CV 草稿（边缘骨架图）地址；AI 生成中做动效用，型号直出为 null */
  draft_url: string | null;
  quality: Quality;
  error: { code: string; message: string; detail?: Record<string, unknown> } | null;
  upstream_calls: number;
  est_cost_cny: number;
  can: {
    select_source: boolean;
    archive: boolean;
    regenerate: boolean;
    cancel: boolean;
  };
};

export type ArchiveListItem = {
  shoe_id: string;
  model_name: string;
  artwork_url: string;
  date_text: string | null;
  date_sort_key: string | null;
  created_at: string;
  has_story: boolean;
};

export type ArchiveListResponse = {
  total: number;
  items: ArchiveListItem[];
  warning?: string | null;
};

export type ArchiveDetail = {
  shoe_id: string;
  model_name: string;
  model_name_input: string;
  artwork_url: string;
  artwork_meta: Record<string, unknown>;
  date_text: string | null;
  date_sort_key: string | null;
  story: string | null;
  created_at: string;
  style_id: string;
  style_version: number;
  source: { provider?: string; url?: string | null; credit?: string } | null;
  quality: { score?: number | null; attempts?: number; checks?: Record<string, number> } | null;
  rights_note: string;
  position?: number | null;
  total?: number | null;
  prev_shoe_id?: string | null;
  next_shoe_id?: string | null;
};

export type DateParseResponse = {
  input: string;
  date_sort_key: string | null;
  kind: string;
  failed: boolean;
  hint: string;
};

export type HealthResponse = {
  status: string;
  version: string;
  env: string;
  providers: { mode: "real" | "mock"; ark: string; search: string };
  flags: { mock_mode: boolean; manual_source_enabled: boolean };
  missing_config: string[];
  notes: string[];
};

// ---------------- 鉴权与邀请码（阶段 4） ----------------
export type LoginOut = {
  owner_id: string;
  role: "guest" | "admin";
  expires_at: string;
  code_expires_at: string | null;
  remaining: number | null;
  message: string;
};

export type MeOut = {
  authenticated: boolean;
  owner_id: string | null;
  role: "guest" | "admin" | null;
  auth_required: boolean;
  remaining: number | null;
  can_generate: boolean;
  code_expires_at: string | null;
  message: string;
};

export type CodeInfo = {
  code: string;
  owner_id: string;
  role: "guest" | "admin";
  max_uses: number | null;
  used_count: number;
  remaining: number | null;
  expires_at: string | null;
  status: "active" | "revoked";
  note: string;
  created_at: string;
  last_used_at: string | null;
  expired: boolean;
  exhausted: boolean;
  archived_count: number;
};
