export type Project = {
  id: string;
  name: string;
  description?: string;
  workspace_type: string;
  status: string;
  member_count: number;
  source_count: number;
};

export type Member = {
  employee_id: string;
  employee_name: string;
  employee_email: string;
  role: string;
};

export type ProjectSource = {
  source_id: string;
  title?: string;
  source_type?: string;
  file_name?: string;
  status: string;
  progress?: number;
  progress_message?: string;
  knowledge_type_name?: string;
  added_at?: string;
};

export type Employee = {
  id: string;
  name: string;
  email: string;
  role: string;
};

export type Source = {
  id: string;
  title?: string;
  source_type?: string;
  status: string;
  knowledge_type_name?: string;
};
