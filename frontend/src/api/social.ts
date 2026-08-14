import api from "./client";

export interface TeamMember {
  avatar_image?: string;
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

export interface NotePerson {
  id: number;
  name: string;
  avatar_color: string;
  avatar_image: string;
}

export interface Note {
  id: number;
  author: number;
  author_name: string;
  subject: number | null;
  title: string;
  body: string;
  /** Empty means the default card. The palette is served with the note. */
  color: string;
  pinned_at: string | null;
  archived_at: string | null;
  /** Turns the note into a reminder and puts it on the calendar. */
  remind_on: string | null;
  people: number[];
  people_detail: NotePerson[];
  is_pinned: boolean;
  is_archived: boolean;
  palette: string[];
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
  async createNote(payload: Partial<Note>) {
    const { data } = await api.post("/auth/notes/", payload);
    return data as Note;
  },
  async updateNote(id: number, payload: Partial<Note>) {
    const { data } = await api.patch(`/auth/notes/${id}/`, payload);
    return data as Note;
  },
  /** Pin, or unpin with `undo`. Re-pinning moves it back to the top. */
  async pinNote(id: number, undo = false) {
    const { data } = await api.post(`/auth/notes/${id}/pin/`, { undo });
    return data as Note;
  },
  async archiveNote(id: number, undo = false) {
    const { data } = await api.post(`/auth/notes/${id}/archive/`, { undo });
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
  async sendMessage(
    recipient: number,
    body: string,
    extra: {
      reply_to?: number | null;
      attachments?: { name: string; mime: string; content: string }[];
    } = {},
  ) {
    const { data } = await api.post("/auth/messages/", { recipient, body, ...extra });
    return data as ChatMessage;
  },

  /** One attachment's bytes from a direct thread the caller is part of. */
  async directAttachment(attachmentId: number) {
    const { data } = await api.get(`/auth/messages/attachment/${attachmentId}/`);
    return data as { name: string; mime: string; content: string };
  },
  async unreadMessages(): Promise<{ total: number; by_sender: Record<string, number> }> {
    const { data } = await api.get("/auth/messages/unread_count/");
    return data;
  },

  // Profile
  async updateMe(payload: Partial<Pick<TeamMember, "name" | "job_title_fa" | "phone" | "avatar_color">> & { display_name_fa?: string }) {
    const { data } = await api.patch("/auth/me/", payload);
    return data;
  },
  async deleteUser(id: number) {
    await api.delete(`/auth/users/${id}/`);
  },
};
