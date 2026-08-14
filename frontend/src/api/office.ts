import api from "./client";

/** A person as every «فرستنده / گیرنده» field renders them. */
export interface Person {
  id: number;
  name: string;
  job_title_fa: string;
  avatar_color: string;
  avatar_image: string;
}

export interface LetterTag {
  id: number;
  name_fa: string;
  color: string;
  letter_count?: number;
}

export interface LetterRecipient {
  id: number;
  user: number;
  user_detail: Person;
  kind: "to" | "cc";
  kind_label: string;
  read_at: string | null;
  archived_at: string | null;
  /** False when a referral deliberately withheld the earlier گردش. */
  sees_history: boolean;
}

export interface LetterAction {
  id: number;
  /** «خصوصی» — only the author and `to_user` may read it. */
  visibility: "all" | "private";
  is_private: boolean;
  letter: number;
  kind: "paraph" | "refer" | "note" | "archive";
  kind_label: string;
  actor: number;
  actor_detail: Person;
  to_user: number | null;
  to_user_detail: Person | null;
  note: string;
  created_at: string;
}

export interface LetterRow {
  id: number;
  number: string;
  subject: string;
  preview: string;
  status: "draft" | "sent";
  sent_at: string | null;
  sender: number;
  sender_detail: Person;
  tags_detail: LetterTag[];
  attachment_count: number;
  recipient_names: string[];
  recipient_count: number;
  read_count: number;
  /** The caller's own copy. Null in صندوق خروجی, where it belongs to others. */
  my_read_at: string | null;
  my_archived_at: string | null;
  in_reply_to: number | null;
}

export interface Letter extends LetterRow {
  body: string;
  recipients: LetterRecipient[];
  actions: LetterAction[];
  attachments: { id: number; name: string; mime: string; size_bytes: number }[];
  in_reply_to_detail: { id: number; number: string; subject: string } | null;
}

export type Box = "inbox" | "outbox" | "paraph" | "archive" | "draft";

export interface Mailbox {
  box: Box;
  count: number;
  /** Unread across the whole inbox, not just this page — drives the badge. */
  unread: number;
  rows: LetterRow[];
}

export interface LetterDraft {
  subject: string;
  body: string;
  to: number[];
  cc: number[];
  tags: number[];
  in_reply_to?: number | null;
  attachments?: { name: string; mime: string; content: string }[];
  send?: boolean;
}

type Params = Record<string, unknown>;

/** Drop empty values so an untouched filter never narrows the mailbox. */
function clean(params: Params): Params {
  return Object.fromEntries(
    Object.entries(params).filter(([, v]) => v !== "" && v !== null && v !== undefined),
  );
}

export const officeApi = {
  async mailbox(box: Box, params: Params = {}): Promise<Mailbox> {
    const { data } = await api.get("/office/mailbox/", {
      params: clean({ box, ...params }),
    });
    return data;
  },

  async letter(id: number): Promise<Letter> {
    const { data } = await api.get(`/office/letters/${id}/`);
    return data;
  },

  async create(draft: LetterDraft): Promise<Letter> {
    const { data } = await api.post("/office/letters/", draft);
    return data;
  },

  async update(id: number, draft: Partial<LetterDraft>): Promise<Letter> {
    const { data } = await api.patch(`/office/letters/${id}/`, draft);
    return data;
  },

  async remove(id: number): Promise<void> {
    await api.delete(`/office/letters/${id}/`);
  },

  async send(id: number): Promise<Letter> {
    const { data } = await api.post(`/office/letters/${id}/send/`);
    return data;
  },

  /** `to` is required when private — see LetterAction.Visibility. */
  async paraph(id: number, note = "", isPrivate = false, to?: number) {
    const { data } = await api.post(`/office/letters/${id}/paraph/`, {
      note, private: isPrivate, to_user: to ?? null,
    });
    return data as LetterAction;
  },

  async refer(id: number, toUser: number, note = "", seesHistory = true) {
    const { data } = await api.post(`/office/letters/${id}/refer/`, {
      to_user: toUser, note, sees_history: seesHistory,
    });
    return data as LetterAction;
  },

  async note(id: number, note: string, isPrivate = false, to?: number) {
    const { data } = await api.post(`/office/letters/${id}/note/`, {
      note, private: isPrivate, to_user: to ?? null,
    });
    return data as LetterAction;
  },

  async archive(id: number, undo = false): Promise<{ archived_at: string | null }> {
    const { data } = await api.post(`/office/letters/${id}/archive/`, { undo });
    return data;
  },

  /**
   * One attachment's bytes. Kept off the list and detail payloads on purpose —
   * a کارتابل of twenty letters would otherwise ship twenty files.
   */
  async attachment(
    letterId: number,
    attId: number,
  ): Promise<{ name: string; mime: string; content: string }> {
    const { data } = await api.get(
      `/office/letters/${letterId}/attachments/${attId}/`,
    );
    return data;
  },

  async people(): Promise<{ people: Person[]; tags: LetterTag[] }> {
    const { data } = await api.get("/office/people/");
    return data;
  },

  async createTag(name_fa: string, color = ""): Promise<LetterTag> {
    const { data } = await api.post("/office/letter-tags/", { name_fa, color });
    return data;
  },
};
