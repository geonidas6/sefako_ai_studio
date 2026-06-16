const API_BASE = '/api';

function getStoredToken() {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem('token');
}

function isTokenExpired(token: string) {
  try {
    const payloadPart = token.split('.')[1];
    if (!payloadPart) return true;
    const normalized = payloadPart.replace(/-/g, '+').replace(/_/g, '/');
    const payload = JSON.parse(atob(normalized));
    if (!payload?.exp) return false;
    return Date.now() >= Number(payload.exp) * 1000;
  } catch {
    return true;
  }
}

function getHeaders() {
  const token = getStoredToken();
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  return headers;
}

export async function downloadFile(path: string, filename?: string) {
  const response = await fetch(`${API_BASE}${path}`, { headers: { ...getHeaders() } });
  if (!response.ok) {
    let errorMsg = 'Une erreur est survenue';
    try {
      const data = await response.json();
      errorMsg = data.detail || errorMsg;
    } catch {}
    throw new Error(errorMsg);
  }
  const blob = await response.blob();
  const url = window.URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename || '';
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.URL.revokeObjectURL(url);
}

export async function request(path: string, options: RequestInit = {}) {
  const url = `${API_BASE}${path}`;
  const response = await fetch(url, {
    ...options,
    headers: {
      ...getHeaders(),
      ...options.headers,
    },
  });

  if (!response.ok) {
    let errorMsg = 'Une erreur est survenue';
    try {
      const data = await response.json();
      errorMsg = data.detail || errorMsg;
    } catch {
      // ignore
    }

    if (response.status === 401 && typeof window !== 'undefined') {
      localStorage.removeItem('token');
      localStorage.removeItem('username');
      window.dispatchEvent(new CustomEvent('aia-auth-expired', { detail: { message: errorMsg } }));
    }
    throw new Error(errorMsg);
  }

  if (response.status === 204) {
    return null;
  }

  return response.json();
}

export const api = {
  auth: {
    async login(username: string, password: string) {
      const formData = new URLSearchParams();
      formData.append('username', username);
      formData.append('password', password);

      const response = await fetch(`${API_BASE}/auth/login`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
        },
        body: formData,
      });

      if (!response.ok) {
        let errorMsg = 'Identifiants incorrects';
        try {
          const data = await response.json();
          errorMsg = data.detail || errorMsg;
        } catch {
          // ignore
        }
        throw new Error(errorMsg);
      }

      const data = await response.json();
      if (typeof window !== 'undefined') {
        localStorage.setItem('token', data.access_token);
        localStorage.setItem('username', data.username);
      }
      return data;
    },

    logout() {
      if (typeof window !== 'undefined') {
        localStorage.removeItem('token');
        localStorage.removeItem('username');
      }
    },

    isLoggedIn() {
      const token = getStoredToken();
      if (!token) return false;
      if (isTokenExpired(token)) {
        if (typeof window !== 'undefined') {
          localStorage.removeItem('token');
          localStorage.removeItem('username');
        }
        return false;
      }
      return true;
    },

    async checkAdminExists() {
      return request('/auth/me');
    }
  },

  projects: {
    async list() {
      return request('/projects');
    },
    async create(title: string, inputText: string) {
      return request('/projects', {
        method: 'POST',
        body: JSON.stringify({ title, input_text: inputText }),
      });
    },
    async get(id: string) {
      return request(`/projects/${id}`);
    },
    async sendMessage(id: string, content: string, author = 'Utilisateur') {
      return request(`/projects/${id}/messages`, {
        method: 'POST',
        body: JSON.stringify({ content, author }),
      });
    },
    async start(id: string) {
      return request(`/projects/${id}/start`, {
        method: 'POST',
      });
    },
    async events(id: string, afterSequence = 0) {
      return request(`/projects/${id}/events?after_sequence=${afterSequence}`);
    },
    async pause(id: string) {
      return request(`/projects/${id}/pause`, {
        method: 'POST',
      });
    },
    async restart(id: string) {
      return request(`/projects/${id}/restart`, {
        method: 'POST',
      });
    },
    async startTechnicalDesign(id: string, approved = false) {
      return request(`/projects/${id}/technical-design/start`, {
        method: 'POST',
        body: JSON.stringify({ approved }),
      });
    },
    async startImplementation(id: string, approved = false) {
      return request(`/projects/${id}/implementation/start`, {
        method: 'POST',
        body: JSON.stringify({ approved }),
      });
    },
    async getWorkspaceTree(id: string) {
      return request(`/projects/${id}/workspace/tree`);
    },
    async getWorkspaceFile(id: string, filePath: string) {
      return request(`/projects/${id}/workspace/file?path=${encodeURIComponent(filePath)}`);
    },
    async saveWorkspaceFile(id: string, filePath: string, content: string) {
      return request(`/projects/${id}/workspace/file`, {
        method: 'PUT',
        body: JSON.stringify({ path: filePath, content }),
      });
    },
    async createWorkspaceEntry(id: string, filePath: string, isDirectory = false, content = '') {
      return request(`/projects/${id}/workspace/create`, {
        method: 'POST',
        body: JSON.stringify({ path: filePath, is_directory: isDirectory, content }),
      });
    },
    async deleteWorkspaceEntry(id: string, filePath: string) {
      return request(`/projects/${id}/workspace/entry?path=${encodeURIComponent(filePath)}`, {
        method: 'DELETE',
      });
    },
    async moveWorkspaceEntry(id: string, oldPath: string, newPath: string) {
      return request(`/projects/${id}/workspace/move`, {
        method: 'POST',
        body: JSON.stringify({ old_path: oldPath, new_path: newPath }),
      });
    },
    async downloadWorkspaceArchive(id: string) {
      return downloadFile(`/projects/${id}/workspace/archive`, `workspace-${id}.zip`);
    },
    async downloadMarkdownExport(id: string) {
      return downloadFile(`/projects/${id}/exports/markdown`, `aia-project-${id}.md`);
    },
    async getWorkspaceHostExportCommand(id: string) {
      return request(`/projects/${id}/workspace/host-export-command`);
    },
    async delete(id: string) {
      return request(`/projects/${id}`, {
        method: 'DELETE',
      });
    }
  },

  admin: {
    async getQwenAuthStatus() {
      return request('/admin/qwen-auth/status');
    },
    async startQwenAuth() {
      return request('/admin/qwen-auth/start', { method: 'POST' });
    },
    async saveQwenCliApiKey(apiKey: string) {
      return request('/admin/qwen-auth/key', {
        method: 'POST',
        body: JSON.stringify({ api_key: apiKey }),
      });
    },
    async getWorkflowSettings() {
      return request('/admin/workflow-settings');
    },
    async updateWorkflowSettings(data: { debate_rounds: number; llm_timeout_seconds: number; final_json_retry_count: number }) {
      return request('/admin/workflow-settings', {
        method: 'PUT',
        body: JSON.stringify(data),
      });
    },
    async getGenerationSettings() {
      return request('/admin/generation-settings');
    },
    async updateGenerationSettings(data: { root_path: string; require_technical_approval: boolean }) {
      return request('/admin/generation-settings', {
        method: 'PUT',
        body: JSON.stringify(data),
      });
    },
    async getDepartments() {
      return request('/admin/departments');
    },
    async updateDepartments(departments: any[]) {
      return request('/admin/departments', {
        method: 'PUT',
        body: JSON.stringify({ departments }),
      });
    },
    async getConfigs() {
      return request('/admin/llm-config');
    },
    async updateConfig(provider: string, data: { is_enabled: boolean; active_model?: string; api_key?: string; requests_per_minute?: number }) {
      return request(`/admin/llm-config/${provider}`, {
        method: 'PUT',
        body: JSON.stringify(data),
      });
    },
    async addModel(provider: string, model: string) {
      return request(`/admin/llm-config/${provider}/models`, {
        method: 'POST',
        body: JSON.stringify({ model }),
      });
    },
    async getAssignments() {
      return request('/admin/llm-config/assignments');
    },
    async updateAssignment(agent: string, provider: string) {
      return request('/admin/llm-config/assignments', {
        method: 'PUT',
        body: JSON.stringify({ agent, provider }),
      });
    },
    async testConnection(provider: string, apiKey: string, model: string) {
      return request('/admin/llm-config/test', {
        method: 'POST',
        body: JSON.stringify({ provider, api_key: apiKey, model }),
      });
    },
    async getCosts() {
      return request('/admin/llm-config/costs');
    }
  }
};
