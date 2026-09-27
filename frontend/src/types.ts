export type ResponseType = "sql" | "rejected" | "clarification" | "schema_answer" | "error";

export interface Optimization {
  formatted_sql: string;
  suggestions: string[];
  index_recommendations: string[];
  plan: string[];
  cost: {
    level: "low" | "medium" | "high";
    full_scans: string[];
    rows_scanned_estimate: number;
    uses_temp_sort: boolean;
  };
  dialects: Record<string, string>;
}

export interface ToolLogEntry {
  tool: string;
  args: Record<string, unknown>;
  summary?: string;
  error?: string;
}

export interface AgentResponse {
  type: ResponseType;
  message: string;
  reason?: string;
  intent?: string | null;
  sql?: string;
  explanation?: string;
  assumptions?: string[];
  notes?: string[];
  warnings?: string[];
  optimization?: Optimization | null;
  input_sql?: string | null;
  tool_log?: ToolLogEntry[];
}

export interface Step {
  node: string;
  label: string;
  detail?: string | string[] | null;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  response?: AgentResponse;
  steps?: Step[];
  pending?: boolean;
  error?: boolean;
}

export interface ThreadSummary {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  running?: boolean;
}

export interface ExecuteResult {
  columns: string[];
  rows: unknown[][];
  row_count: number;
  truncated: boolean;
  elapsed_ms: number;
  warnings: string[];
}

export interface Health {
  llm_ready: boolean;
  llm_error: string | null;
  model: string;
}
