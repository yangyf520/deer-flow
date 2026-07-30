export interface AgentModelSettings {
  temperature?: number | null;
  max_tokens?: number | null;
}

export type ReasoningEffort = "low" | "medium" | "high";

export interface Agent {
  name: string;
  description: string;
  model: string | null;
  tool_groups: string[] | null;
  skills: string[] | null;
  model_settings?: AgentModelSettings | null;
  thinking_enabled?: boolean | null;
  reasoning_effort?: ReasoningEffort | null;
  soul?: string | null;
  knowledge_spaces?: string[] | null;
  knowledge_scenario?: string | null;
  user_id?: string | null;
  created_at?: string | null;
  created_by?: string | null;
}

export interface CreateAgentRequest {
  name: string;
  description?: string;
  model?: string | null;
  tool_groups?: string[] | null;
  skills?: string[] | null;
  model_settings?: AgentModelSettings | null;
  thinking_enabled?: boolean | null;
  reasoning_effort?: ReasoningEffort | null;
  soul?: string;
  knowledge_spaces?: string[] | null;
  knowledge_scenario?: string | null;
}

export interface UpdateAgentRequest {
  description?: string | null;
  model?: string | null;
  tool_groups?: string[] | null;
  skills?: string[] | null;
  model_settings?: AgentModelSettings | null;
  thinking_enabled?: boolean | null;
  reasoning_effort?: ReasoningEffort | null;
  soul?: string | null;
  knowledge_spaces?: string[] | null;
  knowledge_scenario?: string | null;
}
