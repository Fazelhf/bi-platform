import api from "./client";

export interface TeamMember {
  id: number;
  username: string;
  name: string;
  initials: string;
  job_title_fa: string;
  role: string;
  department: string;
  department_label: string;
  avatar_color: string;
  is_online: boolean;
  last_seen: string | null;
  phone: string;
}

export interface Note {
  id: number;
  author: number;
  author_name: string;
  subject: number | null;
  title: string;
  body: string;
  created_at: string;
  updated_at: string;
}

export interface ChatMessage {
  id: number;
  sender: number;
  recipient: number;
  body: string;
  is_read: boolean;
  created_at: string;
}

function unwrap<T>(data: any): T[] {
  return (data?.results ?? data) as T[];
}

export const socialApi = {
  async heartbeat() {
    try { await api.post("/auth/heartbeat/"); } catch { /* ignore */ }
  },

  async team(): Promise<TeamMember[]> {
    const { data } = await api.get("/auth/team/", { params: { page_size: 100 } });
    return unwrap<TeamMember>(data);
  },

  // Notes
  async notes(subject?: number): Promise<Note[]> {
    const { data } = await api.get("/auth/notes/", {
      params: { subject, page_size: 100 },
    });
    return unwrap<Note>(data);
  },
  async createNote(payload: { title?: string; body: string; subject?: number | null }) {
    const { data } = await api.post("/auth/notes/", payload);
    return data as Note;
  },
  async deleteNote(id: number) {
    await api.delete(`/auth/notes/${id}/`);
  },

  // Chat
  async conversation(withUser: number): Promise<ChatMessage[]> {
    const { data } = await api.get("/auth/messages/conversation/", {
      params: { with: withUser },
    });
    return data as ChatMessage[];
  },
  async sendMessage(recipient: number, body: string) {
    const { data } = await api.post("/auth/messages/", { recipient, body });
    return data as ChatMessage;
  },
  async unreadMessages(): Promise<{ total: number; by_sender: Record<string, number> }> {
    const { data } = await api.get("/auth/messages/unread_count/");
    return data;
  },
};
