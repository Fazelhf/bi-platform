import api from "./client";
import type { Person } from "./office";

export interface ProjectMember {
  id: number;
  user: number;
  user_detail: Person;
  role: "manager" | "member";
  role_label: string;
}

export interface Project {
  id: number;
  name: string;
  description: string;
  color: string;
  status: "active" | "done" | "archived";
  status_label: string;
  starts_on: string | null;
  due_on: string | null;
  owner: number | null;
  owner_detail: Person | null;
  memberships: ProjectMember[];
  /** All derived server-side — a stored percentage drifts from its own list. */
  task_count: number;
  done_count: number;
  progress_pct: number;
  overdue_count: number;
  last_done_at: string | null;
  my_open_count: number;
  created_at: string;
}

export interface TaskTag {
  id: number;
  name_fa: string;
  color: string;
}

export interface Task {
  id: number;
  title: string;
  description: string;
  project: number | null;
  project_name: string;
  group: number | null;
  group_name: string;
  assignee: number | null;
  assignee_detail: Person | null;
  creator: number | null;
  creator_detail: Person | null;
  due_on: string | null;
  done_at: string | null;
  priority: "low" | "normal" | "high" | "urgent";
  priority_label: string;
  tags_detail: TaskTag[];
  is_done: boolean;
  is_overdue: boolean;
  days_late: number;
  comment_count: number;
  created_at: string;
}

export interface TaskComment {
  id: number;
  author_detail: Person;
  body: string;
  created_at: string;
}

export type TaskBox = "mine" | "today" | "others" | "done" | "calendar";

export interface TaskBoxData {
  box: TaskBox;
  count: number;
  /** Tab counts, computed server-side — the client only ever sees one page. */
  counts: { mine: number; today: number; overdue: number; others: number };
  rows: Task[];
}

export interface ChatGroup {
  id: number;
  title: string;
  member_count: number;
  members?: Person[];
  unread: number;
  last_message: string;
  last_at: string | null;
}

export interface ChatAttachment {
  id: number;
  name: string;
  mime: string;
  size_bytes: number;
  /** Images render inline; everything else is a download chip. */
  is_image: boolean;
}

export interface ChatReaction {
  emoji: string;
  count: number;
  /** Whether *you* gave this one — the same tap takes it back. */
  mine: boolean;
  who: number[];
}

export interface ChatMessageRow {
  id: number;
  body: string;
  created_at: string;
  edited_at: string | null;
  sender: number;
  sender_detail: Person;
  reply_to: { id: number; body: string; sender_name: string } | null;
  attachments: ChatAttachment[];
  reactions: ChatReaction[];
}

export interface ChatOverview {
  direct: {
    user: Person;
    last_message: string;
    last_at: string;
    unread: number;
  }[];
  groups: ChatGroup[];
  people: Person[];
}

export interface Workbench {
  tiles: { key: string; label: string; value: number; tone?: string }[];
  my_tasks: Task[];
  following: Task[];
  /** Note reminders due within a week — «فردا زنگ بزن» lives in notes. */
  reminders: {
    id: number; title: string; remind_on: string;
    color: string; overdue: boolean;
  }[];
  projects: Project[];
}

export const workApi = {
  // -- projects --------------------------------------------------------
  async projects(): Promise<Project[]> {
    const { data } = await api.get("/office/projects/");
    return data.results ?? data;
  },
  async project(id: number): Promise<Project> {
    const { data } = await api.get(`/office/projects/${id}/`);
    return data;
  },
  async board(id: number): Promise<{
    project: Project;
    groups: { id: number; name: string; tasks: Task[] }[];
    ungrouped: Task[];
  }> {
    const { data } = await api.get(`/office/projects/${id}/board/`);
    return data;
  },
  async saveProject(body: Partial<Project> & { member_ids?: number[] }, id?: number) {
    const { data } = id
      ? await api.patch(`/office/projects/${id}/`, body)
      : await api.post("/office/projects/", body);
    return data as Project;
  },

  // -- tasks -----------------------------------------------------------
  async taskBox(box: TaskBox, params: Record<string, unknown> = {}): Promise<TaskBoxData> {
    const { data } = await api.get("/office/task-box/", { params: { box, ...params } });
    return data;
  },
  async task(id: number): Promise<Task & { comments: TaskComment[] }> {
    const { data } = await api.get(`/office/tasks/${id}/`);
    return data;
  },
  async saveTask(body: Partial<Task>, id?: number): Promise<Task> {
    const { data } = id
      ? await api.patch(`/office/tasks/${id}/`, body)
      : await api.post("/office/tasks/", body);
    return data;
  },
  async removeTask(id: number): Promise<void> {
    await api.delete(`/office/tasks/${id}/`);
  },
  /** Tick off or reopen. The server stamps who and when. */
  async toggleTask(id: number): Promise<Task> {
    const { data } = await api.post(`/office/tasks/${id}/toggle/`);
    return data;
  },
  async commentTask(id: number, body: string): Promise<TaskComment> {
    const { data } = await api.post(`/office/tasks/${id}/comment/`, { body });
    return data;
  },

  // -- chat ------------------------------------------------------------
  async chatOverview(): Promise<ChatOverview> {
    const { data } = await api.get("/office/chat/");
    return data;
  },
  async group(id: number): Promise<ChatGroup & { messages: ChatMessageRow[] }> {
    const { data } = await api.get(`/office/chat-groups/${id}/`);
    return data;
  },
  async createGroup(title: string, members: number[]): Promise<ChatGroup> {
    const { data } = await api.post("/office/chat-groups/", { title, members });
    return data;
  },
  async postToGroup(
    id: number,
    body: string,
    extra: {
      reply_to?: number | null;
      attachments?: { name: string; mime: string; content: string }[];
    } = {},
  ): Promise<ChatMessageRow> {
    const { data } = await api.post(`/office/chat-groups/${id}/post_message/`, {
      body, ...extra,
    });
    return data;
  },

  /** Toggle one emoji on a message; returns the regrouped summary. */
  async react(messageId: number, emoji: string): Promise<{ reactions: ChatReaction[] }> {
    const { data } = await api.post(`/office/chat/messages/${messageId}/`, { emoji });
    return data;
  },

  async chatAttachment(messageId: number, attachmentId: number) {
    const { data } = await api.get(`/office/chat/messages/${messageId}/`, {
      params: { attachment: attachmentId },
    });
    return data as { name: string; mime: string; content: string };
  },
  async groupMembers(id: number, add: number[] = [], remove: number[] = []) {
    const { data } = await api.post(`/office/chat-groups/${id}/members/`, { add, remove });
    return data as ChatGroup;
  },
  async leaveGroup(id: number): Promise<void> {
    await api.post(`/office/chat-groups/${id}/leave/`);
  },

  // -- workbench -------------------------------------------------------
  async workbench(): Promise<Workbench> {
    const { data } = await api.get("/office/workbench/");
    return data;
  },
};
