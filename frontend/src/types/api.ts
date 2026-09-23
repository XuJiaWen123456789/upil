export type Role = "parent" | "teacher";
export type Capability =
  | "chat_access"
  | "learning_read"
  | "report_read"
  | "class_summary_read"
  | "lead_followup";

export interface FrontendBootstrap {
  app_name: string;
  environment: string;
  demo_mode: boolean;
  features: Record<string, boolean>;
}

export interface SessionInfo {
  role: Role;
  permissions: string[];
  capabilities: Capability[];
  demo_user_id: string | null;
}

export interface ConversationSummary {
  conversation_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  last_message_at: string | null;
}

export interface ConversationListResponse {
  items: ConversationSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface ConversationHistoryMessage {
  message_id: number;
  sequence_no: number;
  role: "user" | "assistant";
  content: string;
  created_at: string;
}

export interface ConversationMessagesResponse {
  conversation_id: string;
  items: ConversationHistoryMessage[];
  has_more: boolean;
}

export interface SourceReference {
  source_id?: string | null;
  title?: string | null;
  snippet?: string | null;
  media_asset_id?: string | null;
  score?: number | null;
}

export interface ReportSummary {
  task_id: string;
  task_type: "parent_learning_report" | "teacher_class_learning_report";
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  period_start: string | null;
  period_end: string | null;
  period_type: string | null;
  template_version: string | null;
  created_at: string;
  completed_at: string | null;
  download_available: boolean;
  message: string;
}

export interface ReportArtifact {
  artifact_id: string;
  artifact_type: string;
  created_at: string;
  download_available: boolean;
}

export interface ReportDetail extends ReportSummary {
  artifacts: ReportArtifact[];
}

export interface ReportListResponse {
  items: ReportSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface LearningSnapshot {
  profile: { learner_id: string; learner_name: string; active: boolean };
  balance: { total_hours: number; consumed_hours: number; remaining_hours: number };
  attendance: {
    total_lessons: number;
    present_lessons: number;
    absent_lessons: number;
    leave_lessons: number;
    attendance_rate: number;
    period_start: string | null;
    period_end: string | null;
  };
  progress: Array<{
    course_name: string;
    current_stage: string;
    completion_rate: number;
    strengths: string[];
    next_focus: string[];
    teacher_note: string;
    updated_at: string;
  }>;
}

export interface ClassMetric {
  learner_id: string;
  learner_name: string;
  scheduled_lessons: number;
  marked_lessons: number;
  attended_lessons: number;
  absent_lessons: number;
  excused_lessons: number;
  unmarked_lessons: number;
  completion_rate: number;
  attendance_rate: number;
  remaining_hours: number | null;
}

export interface ClassLearningSummary {
  class_id: string;
  class_name: string;
  course_name: string;
  campus_name: string;
  period_start: string;
  period_end: string;
  scheduled_lessons: number;
  enrolled_learners: number;
  expected_attendance_records: number;
  marked_attendance_records: number;
  attended_records: number;
  absent_records: number;
  excused_records: number;
  unmarked_records: number;
  completion_rate: number;
  attendance_rate: number;
  low_balance_threshold: number;
  missing_hour_accounts: number;
  learner_metrics: ClassMetric[];
  absence_top5: ClassMetric[];
  low_balance_learners: ClassMetric[];
}

export type LeadStrength = "low" | "medium" | "high";
export type LeadDestination = "lead_pool" | "advisor_queue";
export type LeadStatus =
  | "open"
  | "awaiting_contact_consent"
  | "ready_for_followup"
  | "contacted"
  | "trial_scheduled"
  | "enrolled"
  | "closed_won"
  | "closed_lost";

/** 家长聊天只接收安全投影，不包含证据码、内部队列或联系方式明文。 */
export interface LeadChatCard {
  lead_id: string;
  interest_type: "trial" | "enrollment" | "unknown";
  status: LeadStatus | "withdrawn";
  course_name: string;
  contact_masked: string | null;
  prompt: string | null;
}

export interface LeadSummary {
  lead_id: string;
  learner_name: string | null;
  course_name: string;
  interest_type: "trial" | "enrollment" | "unknown";
  strength: LeadStrength;
  destination: LeadDestination;
  status: LeadStatus;
  contact_available: boolean;
  contact_masked: string | null;
  assigned_to_me: boolean;
  created_at: string;
  updated_at: string;
}

export interface LeadFollowUp {
  follow_up_id: number;
  action: string;
  result: string;
  note: string | null;
  next_follow_up_at: string | null;
  created_at: string;
}

export interface LeadDetail extends LeadSummary {
  follow_ups: LeadFollowUp[];
}

export interface LeadListResponse {
  items: LeadSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface LeadContact {
  lead_id: string;
  contact_type: "phone" | "email";
  contact_value: string;
}

export interface LeadFollowUpInput {
  action: "claim" | "contact" | "schedule_trial" | "confirm_enrollment" | "close";
  result: "claimed" | "reached" | "unreachable" | "declined" | "scheduled" | "cancelled" | "enrolled" | "won" | "lost";
  note?: string | null;
  next_follow_up_at?: string | null;
}
